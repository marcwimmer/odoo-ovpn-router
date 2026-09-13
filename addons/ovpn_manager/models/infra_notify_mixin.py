"""Turn writes on access-relevant records into infrastructure notifications.

Models opt in by inheriting this mixin and naming the handful of fields whose
change actually means "somebody can now reach something they could not reach
before". Everything else stays silent on purpose: a channel that reports every
write is a channel nobody reads, and then the one message that mattered scrolls
past unseen.
"""

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class InfraNotifyMixin(models.AbstractModel):
    _name = "infra.notify.mixin"
    _description = "Announce access-relevant changes on the infrastructure topic"

    # Fields worth a notification. Order is the order they appear in the message.
    _infra_fields = ()
    # Subset of the above that goes out loud.
    _infra_high_fields = ()
    # Fields where only the appearance of a value is news. A download link
    # being handed out matters; the same link expiring an hour later is
    # housekeeping, and a cron that clears them every minute would otherwise
    # turn this channel into noise.
    _infra_only_when_set = ()
    _infra_on_create = True
    _infra_on_unlink = True
    # Creating or removing a record is usually routine; models where it is not
    # (a hand-placed public key, say) raise these.
    _infra_create_priority = "default"
    _infra_unlink_priority = "default"
    # Human word for this kind of record, used in the message title.
    _infra_kind = ""

    # ------------------------------------------------------------------
    # helpers a concrete model may override
    # ------------------------------------------------------------------

    def _infra_label(self):
        """How this record is named in a notification."""
        self.ensure_one()
        return self.display_name or "%s#%s" % (self._name, self.id)

    def _infra_value_repr(self, fname):
        """Comparable, human-readable representation of one watched field.

        Relations become a set of names so the message can say "+ marc" instead
        of dumping ids nobody can read on a phone.
        """
        self.ensure_one()
        field = self._fields.get(fname)
        if field is None:
            return None
        value = self[fname]
        if field.type in ("many2many", "one2many"):
            return sorted(record.display_name or str(record.id) for record in value)
        if field.type == "many2one":
            return value.display_name if value else ""
        if field.type == "binary":
            return "<%d bytes>" % len(value or b"")
        if field.type == "boolean":
            # "Active: True -> " reads as a glitch; say what happened.
            return "ja" if value else "nein"
        return value if value not in (None, False) else ""

    def _infra_should_notify(self):
        """Stay quiet while the registry is still coming up.

        Module installs and upgrades write a lot of these records, and none of
        it is a human granting anybody access.
        """
        if not self.env.registry.ready:
            return False
        if self.env.context.get("infra_notify_skip"):
            return False
        if self.env.context.get("install_mode"):
            return False
        return True

    # ------------------------------------------------------------------
    # diffing
    # ------------------------------------------------------------------

    def _infra_snapshot(self, fnames):
        return {
            record.id: {fname: record._infra_value_repr(fname) for fname in fnames}
            for record in self
        }

    @api.model
    def _infra_render_change(self, fname, before, after):
        """One line describing what changed in one field."""
        label = self._fields[fname].string or fname
        if isinstance(before, list) or isinstance(after, list):
            before_set, after_set = set(before or []), set(after or [])
            parts = []
            for name in sorted(after_set - before_set):
                parts.append("+ %s" % name)
            for name in sorted(before_set - after_set):
                parts.append("- %s" % name)
            if not parts:
                return None
            return "%s: %s" % (label, ", ".join(parts))
        if before == after:
            return None
        if fname in self._infra_only_when_set:
            return "%s: erzeugt" % label if after else None
        return "%s: %s → %s" % (
            label,
            before if before != "" else "–",
            after if after != "" else "–",
        )

    def _infra_report(self, before_snapshot):
        after_snapshot = self._infra_snapshot(list(self._infra_fields))
        for record in self:
            before = before_snapshot.get(record.id, {})
            after = after_snapshot.get(record.id, {})
            lines, loud = [], False
            for fname in self._infra_fields:
                if fname not in before:
                    continue
                line = self._infra_render_change(fname, before[fname], after.get(fname))
                if line:
                    lines.append(line)
                    if fname in self._infra_high_fields:
                        loud = True
            if not lines:
                continue
            record._infra_announce(
                _("%s geändert: %s") % (self._infra_kind, record._infra_label()),
                "\n".join(lines),
                priority="high" if loud else "default",
            )

    def _infra_announce(self, title, body, priority="default", tags="key"):
        author = self.env.user.name or self.env.user.login
        body = "%s\n(durch %s)" % (body, author)
        self.env["infra.notify.event"].sudo()._log(
            title, body, priority=priority, tags=tags, record=self
        )

    # ------------------------------------------------------------------
    # ORM hooks
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if self._infra_on_create and records._infra_should_notify():
            for record in records:
                lines = []
                for fname in self._infra_fields:
                    value = record._infra_value_repr(fname)
                    if isinstance(value, list):
                        value = ", ".join(value)
                    if value not in ("", None, False):
                        lines.append(
                            "%s: %s" % (self._fields[fname].string or fname, value)
                        )
                record._infra_announce(
                    _("%s angelegt: %s") % (self._infra_kind, record._infra_label()),
                    "\n".join(lines) or _("(keine weiteren Angaben)"),
                    priority=self._infra_create_priority,
                )
        return records

    def write(self, vals):
        watched = [fname for fname in self._infra_fields if fname in vals]
        notify = bool(watched) and self._infra_should_notify()
        before = self._infra_snapshot(watched) if notify else {}
        result = super().write(vals)
        if notify:
            self._infra_report(before)
        return result

    def unlink(self):
        if self._infra_on_unlink and self._infra_should_notify():
            for record in self:
                record._infra_announce(
                    _("%s gelöscht: %s") % (self._infra_kind, record._infra_label()),
                    _("Datensatz entfernt."),
                    priority=self._infra_unlink_priority,
                )
        return super().unlink()
