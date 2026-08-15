import ipaddress

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OvpnDnsRecord(models.Model):
    """A name the VPN resolves differently than the public DNS does.

    The case this exists for: a service is reachable both from the internet and
    from inside the tunnel, and the public A record has to keep pointing at the
    public address because machines out there depend on it. Clients inside the
    tunnel still want the internal address - otherwise their packets leave
    through their local uplink and arrive with the wrong source address, which
    is exactly what an IP allowlist on the other end rejects.

    A hosts file entry solves that per machine, but only on machines that have
    one. Phones and tablets do not, which is why this belongs on the server.
    """

    _name = "ovpn.dns.record"
    _description = "VPN DNS Override"
    _order = "name"

    name = fields.Char(
        "Hostname",
        required=True,
        help="Fully qualified name, e.g. hosting.zebroo.de. Answered with the "
        "address below for every client using this site's resolver; all other "
        "names are forwarded upstream untouched.",
    )
    ip_address = fields.Char(
        "IP Address",
        required=True,
        help="Address handed out inside the tunnel, usually the host's VPN " "address.",
    )
    site_id = fields.Many2one(
        "ovpn.site", string="Site", required=True, ondelete="cascade"
    )
    active = fields.Boolean(default=True)
    note = fields.Char("Note", help="Why this override exists.")

    _sql_constraints = [
        (
            "name_site_uniq",
            "unique(name, site_id)",
            "There is already an override for this hostname on this site.",
        ),
    ]

    @api.constrains("ip_address")
    def _check_ip_address(self):
        for rec in self:
            try:
                ipaddress.ip_address(rec.ip_address or "")
            except ValueError:
                raise ValidationError(
                    _("'%s' is not a valid IP address.") % rec.ip_address
                )

    @api.constrains("name")
    def _check_name(self):
        for rec in self:
            name = (rec.name or "").strip()
            # dnsmasq takes the name verbatim, so anything that is not a plain
            # hostname would end up in its config as garbage. Catch it here
            # rather than letting the server-side reload fail.
            if not name or " " in name or "/" in name:
                raise ValidationError(_("'%s' is not a valid hostname.") % rec.name)

    def _get_json(self):
        return [
            {"name": (rec.name or "").strip(), "ip": (rec.ip_address or "").strip()}
            for rec in self.filtered("active")
        ]

    def _apply_site(self):
        """Push the change out to the server right away.

        Editing an override without regenerating settings.json would leave the
        record looking effective while nothing changed on the server.
        """
        for site in self.mapped("site_id"):
            site.generate_json()

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._apply_site()
        return recs

    def write(self, vals):
        res = super().write(vals)
        self._apply_site()
        return res

    def unlink(self):
        sites = self.mapped("site_id")
        res = super().unlink()
        for site in sites:
            site.generate_json()
        return res
