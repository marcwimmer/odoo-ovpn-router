from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import ipaddress


class OvpnMember(models.Model):
    _name = "ovpn.member"

    name = fields.Char("Name", required=True)
    partner_id = fields.Many2one("res.partner", string="Partner")
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)
    ip_address = fields.Char("IP Address", required=True)
    is_master = fields.Boolean("Is Master")
    force_remote = fields.Char("Force Remote", help="e.g. 127.0.0.1 1194")

    _sql_constraints = [
        (
            "ip_address_unique",
            "unique(site_id, ip_address)",
            _("Only one unique entry allowed."),
        ),
    ]

    @api.constrains("ip_address")
    def _check_ip(self):
        for rec in self:
            ip = (rec.ip_address or "").strip()
            try:
                ip = ipaddress.IPv4Address(ip)
            except Exception as ex:                
                raise ValidationError(str(ex)) from ex
            rec.site_id.match_ip(ip)
            if str(ip) != rec.ip_address:
                rec.ip_address = str(ip)

    def _get_json(self):
        res = {}
        for rec in self:
            res[rec.ip_address] = [rec.name, rec.partner_id.email]
        return res

    def download_vpn(self):
        pass
