import os
from pathlib import Path
from odoo import _, api, fields, models, SUPERUSER_ID
from pathlib import Path
import arrow
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import ipaddress
import hashlib



class OvpnMember(models.Model):
    _name = "ovpn.member"
    _order = 'is_master, ip_address'

    name = fields.Char("Name", required=True)
    partner_id = fields.Many2one("res.partner", string="Partner")
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)
    ip_address = fields.Char("IP Address", required=True)
    is_master = fields.Boolean("Is Master")
    force_remote = fields.Char("Force Remote", help="e.g. 127.0.0.1 1194")
    cert_content = fields.Binary("Certificate Content", compute="_cert_content", attachment=True)

    _sql_constraints = [
        (
            "ip_address_unique",
            "unique(site_id, ip_address)",
            _("Only one unique entry allowed."),
        ),
    ]

    def _cert_content(self):
        for rec in self:
            file = Path(os.getenv("OVPN_DATA")) / "clients" / f"{rec.name}.conf"
            rec.cert_content = file.read_bytes()

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

    def download_vpn_link(self):
        url = self.env['ir.config_parameter'].get_param(key="web.base.url", default=False)
        time = self._get_time_for_hash()
        url += f'/download/vpn/{self.id}'
        hash = self._get_hash(str(self.id) + time)
        url += f"?hash={hash}"
        return url
        
    @api.model
    def _get_time_for_hash(self):
        return arrow.get().strftime("%Y-%m-%d %H:00:00")

    def _get_hash(self, value):
        my_bytes = value.encode('utf-8')
        my_hash = hashlib.sha512(my_bytes)
        hex_hash = my_hash.hexdigest()
        return hex_hash

    def _get_content(self):
        self.ensure_one()
        file = Path("/tmp/ovpn.data") / 'clients' / f"{self.name}.conf"
        return file.read_bytes()