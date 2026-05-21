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
import random
import string

_TEMP_ADJECTIVES = [
    "brave",
    "calm",
    "eager",
    "fancy",
    "giant",
    "happy",
    "jolly",
    "kind",
    "lively",
    "merry",
    "noble",
    "proud",
    "quiet",
    "rapid",
    "sharp",
    "swift",
    "tidy",
    "vivid",
    "warm",
    "witty",
    "bold",
    "bright",
    "crisp",
    "daring",
    "elite",
    "fierce",
    "grand",
    "hardy",
    "ideal",
    "jade",
]
_TEMP_NOUNS = [
    "falcon",
    "panda",
    "tiger",
    "eagle",
    "shark",
    "wolf",
    "crane",
    "lynx",
    "raven",
    "viper",
    "bison",
    "cobra",
    "dingo",
    "finch",
    "gecko",
    "heron",
    "ibis",
    "jaguar",
    "koala",
    "lemur",
    "manta",
    "otter",
    "puffin",
    "quail",
    "robin",
    "stoat",
    "tapir",
    "vole",
    "wren",
    "zebu",
]


class OvpnMember(models.Model):
    _name = "ovpn.member"
    _order = "is_master, ip_address_sortable"

    active = fields.Boolean("Active", default=True)
    name = fields.Char("Name", required=True)
    partner_id = fields.Many2one("res.partner", string="Partner")
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)
    ip_address_sortable = fields.Char(
        "IP Address", compute="_compute_ip_address", store=True
    )
    ip_address = fields.Char("IP Address")
    is_master = fields.Boolean("Is Master")
    force_remote = fields.Char("Force Remote", help="e.g. 127.0.0.1 1194")
    cert_content = fields.Binary(
        "Certificate Content", compute="_cert_content", attachment=True
    )
    download_hash = fields.Char()
    download_hash_clear_date = fields.Datetime()
    download_link = fields.Char(compute="_compute_download_link", store=False)
    temp_hash = fields.Char("Temp Hash")
    temp_hash_expiry = fields.Datetime("Temp Link Expiry")
    temp_download_link = fields.Char(compute="_compute_temp_download_link", store=False)
    wg_config = fields.Text("WireGuard Config")
    wg_deploy_hash = fields.Char()
    wg_deploy_hash_expiry = fields.Datetime("Deploy Link Expiry")
    wg_deploy_link = fields.Char(compute="_compute_wg_deploy_link", store=False)
    bypass_network_check = fields.Boolean(
        "Bypass Network Check", help="Allow IP outside site network"
    )
    ip_history_ids = fields.One2many(
        "ovpn.member.ip.history", "member_id", string="IP History"
    )

    @api.constrains("name")
    def _check_name(self):
        for rec in self:
            allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ_-1234567890"
            for c in rec.name:
                if c.lower() not in allowed and c.upper() not in allowed:
                    raise ValidationError(f"Not allowed character: {c}")
            for c in "01234567890":
                if rec.name.startswith(c):
                    raise ValidationError("Name cannot start with a number")

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
            if not ip:
                continue
            try:
                ip = ipaddress.IPv4Address(ip)
            except Exception as ex:
                raise ValidationError(str(ex)) from ex
            if not rec.bypass_network_check:
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

    def write(self, vals):
        if "ip_address" in vals and not vals.get("ip_address"):
            # Auto-assign next IP per record (each may have a different site)
            for rec in self:
                assigned = rec.site_id._next_ip()
                if rec.ip_address:
                    self.env["ovpn.member.ip.history"].create(
                        {
                            "member_id": rec.id,
                            "ip_address": rec.ip_address,
                            "change_date": fields.Datetime.now(),
                        }
                    )
                super(OvpnMember, rec).write(dict(vals, ip_address=assigned))
            return True

        if "ip_address" in vals:
            for rec in self:
                if rec.ip_address and rec.ip_address != vals["ip_address"]:
                    self.env["ovpn.member.ip.history"].create(
                        {
                            "member_id": rec.id,
                            "ip_address": rec.ip_address,
                            "change_date": fields.Datetime.now(),
                        }
                    )
        return super().write(vals)

    def _log_initial_ip(self):
        for rec in self:
            if rec.ip_address:
                self.env["ovpn.member.ip.history"].create(
                    {
                        "member_id": rec.id,
                        "ip_address": rec.ip_address,
                        "change_date": fields.Datetime.now(),
                    }
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("ip_address"):
                site_id = vals.get("site_id")
                if site_id:
                    site = self.env["ovpn.site"].browse(site_id)
                    vals["ip_address"] = site._next_ip()
        records = super().create(vals_list)
        records._log_initial_ip()
        return records

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
        url += f"/download/byhash/vpn/{self.download_hash}"
        hash = self._get_hash(str(self.id) + time)
        url += f"?hash={hash}"
        return url

    def download(self):
        self.ensure_one()
        self.download_hash = str(uuid.uuid4())
        expiration_minutes = int(
            self.env["ir.config_parameter"].get_param(
                key="ovpn.download_hash_expiration_time", default=30
            )
        )
        self.download_hash_clear_date = (
            arrow.utcnow()
            .shift(minutes=expiration_minutes)
            .strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        )
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
        return self.wg_config.encode("utf-8")

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if self.env.context.get("default_site_id"):
            site = self.env["ovpn.site"].browse(self.env.context["default_site_id"])

            res["ip_address"] = site._next_ip()
        return res

    @api.onchange("site_id")
    def _changed_site(self):
        if self.site_id:
            self.ip_address = self.site_id._next_ip()

    @api.model
    def _clear_downloads(self):
        for member in self.search([]):
            if (
                not member.download_hash_clear_date
                or member.download_hash_clear_date < arrow.utcnow().naive
            ):
                member.download_hash_clear_date = False
                member.download_hash = False

    def _generate_temp_hash(self):
        safe_chars = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i
        suffix = "".join(random.choices(safe_chars, k=4))
        return (
            f"{random.choice(_TEMP_ADJECTIVES)}-{random.choice(_TEMP_NOUNS)}-{suffix}"
        )

    def generate_temp_link(self):
        self.ensure_one()
        self.temp_hash = self._generate_temp_hash()
        self.temp_hash_expiry = (
            arrow.utcnow().shift(minutes=2).strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        )

    @api.depends("temp_hash")
    def _compute_temp_download_link(self):
        for rec in self:
            url = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(key="web.base.url", default="")
            )
            if not rec.temp_hash:
                rec.temp_download_link = False
            else:
                rec.temp_download_link = f"{url}/vpn/temp/{rec.temp_hash}"

    def generate_wg_deploy_link(self):
        self.ensure_one()
        self.wg_deploy_hash = self._generate_temp_hash()
        self.wg_deploy_hash_expiry = (
            arrow.utcnow().shift(minutes=10).strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        )

    @api.depends("wg_deploy_hash")
    def _compute_wg_deploy_link(self):
        for rec in self:
            url = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(key="web.base.url", default="")
            )
            if not rec.wg_deploy_hash:
                rec.wg_deploy_link = False
            else:
                rec.wg_deploy_link = f"{url}/vpn/deploy/{rec.wg_deploy_hash}"

    @api.depends("download_hash")
    def _compute_download_link(self):
        for rec in self:
            url = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(key="web.base.url", default=False)
            )
            if not rec.download_hash:
                rec.download_link = False
            else:
                rec.download_link = (
                    (url or "") + "/download/byhash/vpn/" + rec.download_hash
                )
