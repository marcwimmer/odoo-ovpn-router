import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import formataddr

# Recipients typed by hand may be separated by comma, semicolon or whitespace.
_EMAIL_SEPARATOR = re.compile(r"[,;\s]+")

_DEFAULT_BODY = """<p>Hallo,</p>
<p>hier das aktuelle Download-Passwort fuer den VPN-Zugang (Site {site}):</p>
<p style="font-size: 16px;"><b>{password}</b></p>
<p>Mit diesem Passwort wird der pers&#246;nliche Zugangs-Link freigeschaltet.
Das Passwort wird regelm&#228;&#223;ig erneuert - bitte den Link zeitnah verwenden.</p>
<p>Viele Gr&#252;&#223;e</p>
<hr/>
<p>Hello,</p>
<p>here is the current download password for the VPN access (site {site}):</p>
<p style="font-size: 16px;"><b>{password}</b></p>
<p>This password unlocks your personal access link. It is renewed regularly,
so please use the link soon.</p>
<p>Best regards</p>"""


class OvpnSitePasswordMail(models.TransientModel):
    _name = "ovpn.site.password.mail"
    _description = "Send the site download password by mail"

    site_id = fields.Many2one("ovpn.site", string="Site", required=True, readonly=True)
    member_ids = fields.Many2many(
        "ovpn.member",
        string="Members",
        domain="[('site_id', '=', site_id)]",
        help="The password is sent to the partner mail address of these members.",
    )
    partner_ids = fields.Many2many("res.partner", string="Additional contacts")
    extra_emails = fields.Char(
        "Additional mail addresses",
        help="Free mail addresses, separated by comma or semicolon.",
    )
    recipient_preview = fields.Text(
        "Recipients", compute="_compute_recipient_preview", readonly=True
    )
    subject = fields.Char("Subject", required=True)
    body = fields.Html(
        "Message",
        sanitize_style=True,
        help="Placeholders: {password} is replaced by the current site password, "
        "{site} by the site name. Keep {password} in the text.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        site = self.env["ovpn.site"].browse(
            res.get("site_id") or self.env.context.get("default_site_id")
        )
        if not site.exists():
            return res
        res.setdefault("site_id", site.id)
        if "subject" in fields_list:
            res.setdefault(
                "subject", _("VPN download password - %s") % (site.name or "")
            )
        if "body" in fields_list:
            res.setdefault("body", _DEFAULT_BODY)
        return res

    @api.depends("member_ids", "partner_ids", "extra_emails")
    def _compute_recipient_preview(self):
        for wizard in self:
            recipients, missing = wizard._collect_recipients()
            lines = [
                "%s <%s>" % (name, mail) if name else mail for name, mail in recipients
            ]
            if missing:
                lines.append(_("Without mail address: %s") % ", ".join(missing))
            wizard.recipient_preview = "\n".join(lines)

    def _collect_recipients(self):
        """Return ([(name, email)], [names without mail address])."""
        self.ensure_one()
        recipients = []
        missing = []
        seen = set()

        def add(name, email):
            email = (email or "").strip()
            if not email or email.lower() in seen:
                return
            seen.add(email.lower())
            recipients.append((name or "", email))

        for member in self.member_ids:
            email = member.partner_id.email
            if not email:
                missing.append(member.display_name)
                continue
            add(member.partner_id.name or member.display_name, email)
        for partner in self.partner_ids:
            if not partner.email:
                missing.append(partner.display_name)
                continue
            add(partner.name, partner.email)
        for email in _EMAIL_SEPARATOR.split(self.extra_emails or ""):
            add("", email)
        return recipients, missing

    def _sender_addresses(self):
        """Return (email_from, reply_to).

        Office 365 only lets us send as the mailbox the outgoing server is
        authenticated with - anything else is rejected with SendAsDenied. So
        the mail goes out from that mailbox and the acting user is put into
        Reply-To.
        """
        self.ensure_one()
        author = self.env.user.partner_id
        reply_to = author.email_formatted or self.env.company.email
        server = (
            self.env["ir.mail_server"].sudo().search([], order="sequence, id", limit=1)
        )
        allowed = (server.from_filter or "").strip()
        # from_filter may also hold a whole domain - then the user address is fine.
        if "@" in allowed and allowed.lower() != (author.email or "").strip().lower():
            return formataddr((author.name, allowed)), reply_to
        return reply_to or allowed, reply_to

    def action_send(self):
        self.ensure_one()
        site = self.site_id
        password = site.one_time_password
        if not password:
            raise UserError(_("This site has no password - generate one first."))

        recipients, missing = self._collect_recipients()
        if missing:
            raise UserError(
                _(
                    "No mail address for: %s\n\n"
                    "Please maintain the address or remove the recipient."
                )
                % ", ".join(missing)
            )
        if not recipients:
            raise UserError(_("Please choose at least one recipient."))

        body = self.body or _DEFAULT_BODY
        if "{password}" not in body:
            raise UserError(
                _("The placeholder {password} is missing in the message text.")
            )
        body = body.replace("{password}", password).replace("{site}", site.name or "")

        author = self.env.user.partner_id
        email_from, reply_to = self._sender_addresses()
        Mail = self.env["mail.mail"].sudo()
        failed = []
        sent = []
        for name, email in recipients:
            mail = Mail.create(
                {
                    "subject": self.subject,
                    "body_html": body,
                    "email_to": ('"%s" <%s>' % (name, email)) if name else email,
                    "author_id": author.id,
                    "email_from": email_from,
                    "reply_to": reply_to,
                    "auto_delete": False,
                }
            )
            mail.send(raise_exception=False)
            if mail.state == "sent":
                sent.append(email)
            else:
                failed.append((email, mail.failure_reason or _("unknown reason")))

        if sent:
            site.message_post(
                body=_("Download password sent by mail to: %s") % ", ".join(sent)
            )
        if failed and not sent:
            # Nothing went out - roll the mails back and show why.
            raise UserError(
                _("Mail could not be sent:\n\n%s")
                % "\n".join("%s: %s" % (mail, reason) for mail, reason in failed)
            )
        if failed:
            site.message_post(
                body=_("Password mail failed for: %s")
                % ", ".join(mail for mail, _reason in failed)
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "warning",
                    "sticky": True,
                    "title": _("Partly sent"),
                    "message": _("Sent: %s\nFailed: %s")
                    % (
                        ", ".join(sent),
                        "; ".join(
                            "%s (%s)" % (mail, reason) for mail, reason in failed
                        ),
                    ),
                },
            }
        return {"type": "ir.actions.act_window_close"}
