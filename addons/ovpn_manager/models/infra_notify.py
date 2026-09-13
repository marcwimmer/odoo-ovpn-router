"""Announce access-relevant changes on a private ntfy topic.

Why a stored row and not a plain HTTP call at the point of change: a permission
change nobody hears about is the exact thing this code exists to prevent, so
the statement "this has to be told" must survive a flaky network, a restarted
worker and a rolled back transaction. The event row is written inside the very
transaction that changed the permission - roll that back and the announcement
disappears with it, which is correct - while the HTTP call happens after the
commit and is retried by cron until it lands.

The second reason is that the rows are the audit trail. "Who was given access
to what, when, by whom" is a question we get asked, and answering it from a
list view beats grepping a phone.
"""

import json
import logging
import urllib.error
import urllib.request

import odoo
from odoo import SUPERUSER_ID, _, api, fields, models

_logger = logging.getLogger(__name__)

URL_PARAM = "infra.notify.ntfy_url"
TOKEN_PARAM = "infra.notify.ntfy_token"
SOURCE_PARAM = "infra.notify.source"

# After this many failed attempts an event stops being retried. At the cron
# cadence below that is roughly a day of trying, which is long enough to ride
# out an ntfy outage and short enough that a misconfigured URL does not have
# the cron hammering it forever.
MAX_ATTEMPTS = 24

# ntfy rejects anything longer outright; its own limit is a little higher, this
# leaves room for the title and keeps a notification readable on a phone.
MAX_MESSAGE_CHARS = 3500

# ntfy's JSON API wants a number here, our users want a word.
_PRIORITY_MAP = {"low": 2, "default": 3, "high": 4, "urgent": 5}


class InfraNotifyEvent(models.Model):
    _name = "infra.notify.event"
    _description = "Infrastructure change announced on the ntfy topic"
    _order = "id desc"

    title = fields.Char("Title", required=True)
    body = fields.Text("Message", required=True)
    priority = fields.Selection(
        [
            ("low", "Low"),
            ("default", "Default"),
            ("high", "High"),
            ("urgent", "Urgent"),
        ],
        default="default",
        required=True,
    )
    tags = fields.Char("Tags", default="key")
    model_name = fields.Char("Model")
    res_id = fields.Integer("Record ID")
    author_id = fields.Many2one(
        "res.users",
        string="Changed by",
        default=lambda self: self.env.user.id,
        ondelete="set null",
    )
    state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        default="pending",
        required=True,
        index=True,
    )
    attempts = fields.Integer("Attempts", default=0)
    send_error = fields.Char("Last Error")
    sent_on = fields.Datetime("Sent On")

    # ------------------------------------------------------------------
    # writing events
    # ------------------------------------------------------------------

    @api.model
    def _log(self, title, body, priority="default", tags="key", record=None):
        """Record one change and arrange for it to be pushed after commit."""
        vals = {
            "title": title,
            "body": body,
            "priority": priority,
            "tags": tags,
        }
        if record is not None and len(record) == 1:
            vals["model_name"] = record._name
            vals["res_id"] = record.id
        event = self.sudo().create(vals)
        event._schedule_flush()
        return event

    def _schedule_flush(self):
        """Push once the current transaction is safely committed.

        Doing it inline would announce changes that a later error rolls back,
        and would let a hanging ntfy stall a write on a hostgroup.
        """
        cr = self.env.cr
        if getattr(cr, "_infra_flush_scheduled", False):
            return
        cr._infra_flush_scheduled = True
        dbname = cr.dbname

        def _flush():
            try:
                cr._infra_flush_scheduled = False
            except Exception:  # pragma: no cover - cursor already gone
                pass
            try:
                with odoo.registry(dbname).cursor() as new_cr:
                    env = api.Environment(new_cr, SUPERUSER_ID, {})
                    env["infra.notify.event"]._send_pending()
            except Exception:
                # The row is stored and the retry cron will pick it up; losing
                # the push must never surface as an error on the user's write.
                _logger.exception("infra notify: post-commit flush failed")

        cr.postcommit.add(_flush)

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------

    @api.model
    def _get_target(self):
        """Return (base_url, topic, token) or None when not configured.

        The parameter holds the full topic URL because that is how the older
        ssh_access notifications are configured and it keeps one obvious knob;
        ntfy's JSON endpoint however wants the base and the topic apart.
        """
        icp = self.env["ir.config_parameter"].sudo()
        url = (icp.get_param(URL_PARAM) or "").strip().rstrip("/")
        if not url:
            return None
        base, _sep, topic = url.rpartition("/")
        if not base or not topic:
            _logger.warning("infra notify: %s is not a topic URL: %s", URL_PARAM, url)
            return None
        return base, topic, (icp.get_param(TOKEN_PARAM) or "").strip()

    @api.model
    def _send_pending(self, limit=200):
        """Push everything not yet delivered, coalesced into one message.

        Coalescing matters: the host agents push their user and group state
        every minute, so a single rebuilt host can produce a burst of events.
        One notification listing them beats twenty buzzes.
        """
        events = self.sudo().search(
            [("state", "!=", "sent"), ("attempts", "<", MAX_ATTEMPTS)],
            order="id asc",
            limit=limit,
        )
        if not events:
            return True
        target = self._get_target()
        if not target:
            # Unconfigured instance (a dev copy, say). Stay quiet and keep the
            # rows - they are still the audit trail.
            return False
        base, topic, token = target
        title, body, priority, tags = events._build_message()
        payload = {
            "topic": topic,
            "title": title,
            "message": body,
            "priority": _PRIORITY_MAP.get(priority, 3),
            # An array, not a comma string - ntfy answers 400 to the latter.
            "tags": [tag for tag in tags.split(",") if tag],
        }
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer %s" % token
        try:
            req = urllib.request.Request(
                base,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status >= 300:
                    raise urllib.error.HTTPError(
                        base, response.status, "unexpected status", None, None
                    )
        except Exception as exc:
            _logger.warning("infra notify: push failed: %s", exc)
            for event in events:
                event.write(
                    {
                        "attempts": event.attempts + 1,
                        "state": "failed",
                        "send_error": str(exc)[:250],
                    }
                )
            return False
        events.write(
            {
                "state": "sent",
                "sent_on": fields.Datetime.now(),
                "send_error": False,
            }
        )
        return True

    def _build_message(self):
        """Fold the selected events into one ntfy message.

        Kept deliberately terse. This channel says "X may now reach Y", which
        is reconnaissance material - it names the group and the person, never
        a host inventory or a key.
        """
        source = (
            self.env["ir.config_parameter"].sudo().get_param(SOURCE_PARAM) or "hosting"
        )
        if any(event.priority == "urgent" for event in self):
            priority = "urgent"
        elif any(event.priority == "high" for event in self):
            priority = "high"
        elif all(event.priority == "low" for event in self):
            priority = "low"
        else:
            priority = "default"
        tags = sorted(
            {tag for event in self for tag in (event.tags or "").split(",") if tag}
        )
        if len(self) == 1:
            title = "[%s] %s" % (source, self.title)
            body = self.body or ""
        else:
            title = "[%s] %d Änderungen" % (source, len(self))
            body = "\n\n".join(
                "%s\n%s" % (event.title, event.body or "") for event in self
            )
        if len(body) > MAX_MESSAGE_CHARS:
            # ntfy refuses oversized messages outright, and a notification
            # nobody can receive is worse than a shortened one. The full text
            # stays on the event record.
            body = body[:MAX_MESSAGE_CHARS] + "\n… (gekürzt, Rest in Odoo)"
        return title, body, priority, ",".join(tags) or "key"

    # ------------------------------------------------------------------
    # crons
    # ------------------------------------------------------------------

    @api.model
    def _cron_send_pending(self):
        """Catch whatever the post-commit push could not deliver."""
        return self._send_pending()

    @api.model
    def _cron_digest(self):
        """Daily recap, so a silently lost push does not mean a blind spot.

        A push channel that fails quietly reads as "nothing happened", which
        is the worst possible failure mode for this particular channel.
        """
        since = fields.Datetime.subtract(fields.Datetime.now(), days=1)
        events = self.sudo().search([("create_date", ">=", since)], order="id asc")
        if not events:
            return True
        lines = []
        for event in events:
            mark = "" if event.state == "sent" else " (nicht zugestellt!)"
            lines.append("- %s%s" % (event.title, mark))
        undelivered = events.filtered(lambda e: e.state != "sent")
        self._log(
            "Tagesrückblick: %d Änderungen" % len(events),
            "\n".join(lines),
            priority="high" if undelivered else "low",
            tags="clipboard",
        )
        return True
