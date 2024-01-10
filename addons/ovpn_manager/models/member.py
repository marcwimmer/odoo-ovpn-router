import os
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT
import uuid
from pathlib import Path
from odoo import _, api, fields, models, SUPERUSER_ID
from pathlib import Path
import arrow
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import ipaddress
import hashlib


class OvpnMember(models.Model):
    _name = "ovpn.member"
    _order = "is_master, ip_address_sortable"

    name = fields.Char("Name", required=True)
    partner_id = fields.Many2one("res.partner", string="Partner")
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)
    ip_address_sortable = fields.Char(
        "IP Address", compute="_compute_ip_address", store=True
    )
    ip_address = fields.Char("IP Address", required=True)
    is_master = fields.Boolean("Is Master")
    force_remote = fields.Char("Force Remote", help="e.g. 127.0.0.1 1194")
    cert_content = fields.Binary(
        "Certificate Content", compute="_cert_content", attachment=True
    )
    download_hash = fields.Char()
    download_hash_clear_date = fields.Datetime()
    download_link = fields.Char(compute="_compute_download_link")

    @api.constrains("name")
    def _check_name(self):
        for rec in self:
            allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ_-"
            for c in rec.name:
                if c.lower() not in allowed and c.upper() not in allowed:
                    raise ValidationError(f"Not allowed character: {c}")

    @api.depends("ip_address")
    def _compute_ip_address(self):
        for rec in self:
            s = (rec.ip_address or "").split(".")
            if not s:
                rec.ip_address_sortable = ""
                continue

            def convert(x):
                x = str(x).zfill(3)
                return x

            s2 = ".".join(list(map(convert, s)))
            rec.ip_address_sortable = s2

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

            duplicate = self.search(
                [
                    ("id", "!=", rec.id),
                    ("ip_address", "=", str(ip)),
                    ("site_id", "=", rec.site_id.id),
                ]
            )
            if duplicate:
                raise ValidationError(f"Duplicate IP Address: {ip}")

    def _get_json(self):
        res = {}
        for rec in self:
            res[rec.ip_address] = [rec.name, rec.partner_id.email]
        return res

    def download_vpn_link(self):
        url = self.env["ir.config_parameter"].get_param(
            key="web.base.url", default=False
        )
        time = self._get_time_for_hash()
        url += f"/download/vpn/{self.id}"
        hash = self._get_hash(str(self.id) + time)
        url += f"?hash={hash}"
        return url

    def download(self):
        self.ensure_one()
        self.download_hash = str(uuid.uuid4())
        self.download_hash_clear_date = arrow.utcnow().shift(minutes=30).strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        return {
            "type": "ir.actions.act_url",
            "url": self.download_vpn_link(),
            "target": "self",
        }

    @api.model
    def _get_time_for_hash(self):
        return arrow.get().strftime("%Y-%m-%d %H:00:00")

    def _get_hash(self, value):
        my_bytes = value.encode("utf-8")
        my_hash = hashlib.sha512(my_bytes)
        hex_hash = my_hash.hexdigest()
        return hex_hash

    def _get_content(self):
        self.ensure_one()
        file = Path("/tmp/ovpn.data") / "clients" / f"{self.name}.conf"
        return file.read_bytes()

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if self.env.context.get('default_site_id'):
            site = self.env['ovpn.site'].browse(
                self.env.context['default_site_id']
            )

            res['ip_address'] = site._next_ip()
        return res

    @api.onchange("site_id")
    def _changed_site(self):
        if self.site_id:
            self.ip_address = self.site_id._next_ip()
    
    @api.model
    def _clear_downloads(self):
        for member in self.search([('download_hash_clear_date', '!=', False)]):
            if member.download_hash_clear_date > arrow.utcnow().datetime:
                member.download_hash_clear_date = False

    def _compute_download_link(self):
        for rec in self:
            url = self.env['ir.config_parameter'].sudo().get_param(key="web.base.url", default=False)
            if not rec.download_hash:
                rec.download_link = False
            else:
                rec.download_link = (url or '') + "/download/byhash/vpn/" + rec.download_hash