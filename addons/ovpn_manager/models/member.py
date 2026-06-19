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
import re
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
    site_one_time_password = fields.Char(
        "Site Download Password",
        related="site_id.one_time_password",
        readonly=True,
    )
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
    download_hash_clear_date = fields.Datetime(
        "Aktueller Link läuft ab am",
        help="Status (automatisch): Ablaufzeitpunkt des zuletzt per 'Download' "
        "erzeugten Links. Danach wird der Link automatisch ungültig. Wird beim "
        "Klick auf 'Download' gesetzt – entweder aus dem unten vorgegebenen "
        "Ablaufdatum oder aus der Standarddauer (Default 30 Min).",
    )
    download_link = fields.Char(compute="_compute_download_link", store=False)
    temp_hash = fields.Char("Temp Hash")
    temp_hash_expiry = fields.Datetime("Temp Link Expiry")
    temp_download_link = fields.Char(compute="_compute_temp_download_link", store=False)
    wg_private_key = fields.Char(
        "WG Private Key (legacy)",
        help="Leer lassen für den neuen Provisioning-Flow — dann erzeugt das "
        "Install-Script den Private Key lokal beim Client. Nur ältere Members "
        "haben hier noch einen Wert.",
    )
    wg_public_key = fields.Char(
        "WG Public Key (Client)",
        help="Wird beim Provisioning vom Client via /vpn/register-pubkey "
        "zurückgemeldet.",
    )
    wg_preshared_key = fields.Char("WG Preshared Key")
    wg_config = fields.Text(
        "WireGuard Config",
        compute="_compute_wg_config",
        store=True,
    )
    wg_deploy_hash = fields.Char()
    wg_deploy_hash_expiry = fields.Datetime("Deploy Link Expiry")
    download_expiry = fields.Datetime(
        "Ablaufdatum vorgeben (optional)",
        help="Eingabe (optional): Bis wann der nächste über 'Download' erzeugte "
        "Link gültig sein soll. Leer lassen = Standarddauer (Systemparameter "
        "'ovpn.download_hash_expiration_time', Default 30 Min). Ein hier gesetztes "
        "(zukünftiges) Datum überschreibt die Standarddauer.",
    )
    wg_deploy_link = fields.Char(compute="_compute_wg_deploy_link", store=False)
    wg_register_token = fields.Char()
    wg_register_token_expiry = fields.Datetime("Register Token Expiry")
    wg_provisioning_state = fields.Selection(
        [
            ("legacy", "Legacy (PrivKey in Odoo)"),
            ("provisioned", "Provisioned"),
            ("pending", "Pending (waiting for client)"),
        ],
        compute="_compute_wg_provisioning_state",
        store=False,
    )
    install_script_preview = fields.Text(
        "Install Script",
        compute="_compute_install_script_preview",
        store=False,
        help="The bash script the member would receive via /vpn/deploy/<hash> | bash.",
    )
    bypass_network_check = fields.Boolean(
        "Bypass Network Check", help="Allow IP outside site network"
    )
    use_wstunnel = fields.Boolean(
        "Use wstunnel (TCP/443)",
        help="Tunnel WG over WSS via wstunnel — for clients whose firewall blocks UDP.",
    )
    deliver_full_conf = fields.Boolean(
        "Deliver full .conf (iPhone)",
        help="Generate a keypair server-side and deliver the complete WireGuard "
        ".conf (with PrivateKey) on download. Needed for clients like the iPhone "
        "WireGuard app that cannot run the install script. Breaks the "
        "'PrivateKey never leaves the client' guarantee — only enable when "
        "necessary.",
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
        result = super().write(vals)
        if "deliver_full_conf" in vals and vals.get("deliver_full_conf"):
            self._ensure_iphone_keypair()
        return result

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

    @staticmethod
    def _generate_psk():
        import secrets
        import base64

        return base64.b64encode(secrets.token_bytes(32)).decode()

    @staticmethod
    def _generate_wg_keypair():
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
        )
        from cryptography.hazmat.primitives import serialization
        import base64

        priv_obj = X25519PrivateKey.generate()
        priv_bytes = priv_obj.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_bytes = priv_obj.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return (
            base64.b64encode(priv_bytes).decode(),
            base64.b64encode(pub_bytes).decode(),
        )

    def _ensure_iphone_keypair(self):
        for rec in self:
            if rec.deliver_full_conf and not rec.wg_private_key:
                priv, pub = self._generate_wg_keypair()
                rec.wg_private_key = priv
                rec.wg_public_key = pub

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("ip_address"):
                site_id = vals.get("site_id")
                if site_id:
                    site = self.env["ovpn.site"].browse(site_id)
                    vals["ip_address"] = site._next_ip()
            if not vals.get("wg_preshared_key"):
                vals["wg_preshared_key"] = self._generate_psk()
            if vals.get("deliver_full_conf") and not vals.get("wg_private_key"):
                priv, pub = self._generate_wg_keypair()
                vals["wg_private_key"] = priv
                vals["wg_public_key"] = pub
        records = super().create(vals_list)
        records._log_initial_ip()
        return records

    def apply_site(self):
        self.ensure_one()
        self.site_id.generate_json()

    def _get_json(self):
        res = {}
        for rec in self:
            res[rec.ip_address] = {
                "name": rec.name,
                "email": rec.partner_id.email or "",
                "public_key": rec.wg_public_key or "",
                "preshared_key": rec.wg_preshared_key or "",
            }
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
        if self.download_expiry and self.download_expiry > fields.Datetime.now():
            # Vom User am Member gewähltes Ablaufdatum hat Vorrang und
            # überschreibt die Standard-Gültigkeitsdauer (Default 30 Min).
            self.download_hash_clear_date = self.download_expiry
        else:
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

    def _wstunnel_params(self):
        """(wss_endpoint, http_upgrade_path_prefix, wstunnel_version) for the site."""
        site = self.site_id
        host = site.wstunnel_host or "vpn.zebroo.de"
        ws_port = site.wstunnel_port or 443
        prefix = site.wstunnel_path_prefix or "wgws"
        version = site.wstunnel_version or "v10.5.5"
        port_suffix = "" if ws_port == 443 else f":{ws_port}"
        return f"wss://{host}{port_suffix}", prefix, version

    def _wg_endpoint_port(self, config):
        """WG server port read from a config's Endpoint line (what the server
        actually listens on); falls back to the site default."""
        m = re.search(r"(?m)^Endpoint = [^:\s]+:(\d+)", config)
        return int(m.group(1)) if m else (self.site_id.wg_server_port or 51820)

    def _endpoint_to_localhost(self, config, port):
        """Point the WG Endpoint at the local wstunnel listener (127.0.0.1)."""
        line = f"Endpoint = 127.0.0.1:{port}"
        if re.search(r"(?m)^Endpoint = .*$", config):
            return re.sub(r"(?m)^Endpoint = .*$", line, config)
        # No Endpoint line (shouldn't happen — _compute_wg_config always adds one);
        # append one so the result stays a valid tunnel config.
        return config.rstrip() + "\n" + line + "\n"

    def _get_tcp_content(self):
        """WireGuard config for the TCP/WSS (wstunnel) mode.

        Same config as _get_content but the Endpoint points at the local
        wstunnel client (127.0.0.1) instead of the server. A comment header
        documents the wstunnel command so a GUI user knows what to run.
        Slower than plain UDP, but gets through hotel / captive networks
        that only allow TCP 443.
        """
        self.ensure_one()
        if not self.wg_config:
            raise UserError(_("Member %s has no WireGuard config yet.") % self.name)
        config = self.wg_config.strip()
        port = self._wg_endpoint_port(config)
        tcp_config = self._endpoint_to_localhost(config, port)
        endpoint, prefix, version = self._wstunnel_params()
        header = (
            "# === TCP / WSS mode (WireGuard over TLS, port 443) ===\n"
            "# Slower, but works through restrictive networks (hotels, captive\n"
            "# portals) that only allow TCP 443. Requires the wstunnel client\n"
            "# running locally before this tunnel is activated:\n"
            "#\n"
            f"#   wstunnel client --connection-min-idle 5 -P {prefix} \\\n"
            f"#     -L udp://{port}:127.0.0.1:{port}?timeout_sec=0 {endpoint}\n"
            "#\n"
            f"# Install wstunnel ({version}): https://github.com/erebe/wstunnel/releases\n"
            "# (macOS: brew install wstunnel). Start it, then activate this tunnel.\n"
            "#\n"
        )
        return (header + tcp_config + "\n").encode("utf-8")

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

    @api.depends("wg_private_key", "wg_public_key")
    def _compute_wg_provisioning_state(self):
        for rec in self:
            if rec.wg_private_key:
                rec.wg_provisioning_state = "legacy"
            elif rec.wg_public_key:
                rec.wg_provisioning_state = "provisioned"
            else:
                rec.wg_provisioning_state = "pending"

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

    @api.depends(
        "wg_private_key",
        "wg_public_key",
        "wg_preshared_key",
        "ip_address",
        "site_id.wg_server_public_key",
        "site_id.wg_server_port",
        "site_id.remote",
        "site_id.wg_allowed_ips",
        "site_id.netmask_int",
    )
    def _compute_wg_config(self):
        for rec in self:
            if not (
                rec.wg_private_key
                and rec.ip_address
                and rec.site_id
                and rec.site_id.wg_server_public_key
            ):
                rec.wg_config = False
                continue
            prefix = rec.site_id.netmask_int or 32
            allowed = rec.site_id.wg_allowed_ips or "10.222.0.0/22"
            port = rec.site_id.wg_server_port or 51820
            # PSK is only emitted when the member has a wg_public_key — that's
            # the marker for "server-side peer config also carries PSK"
            # (apply-clients.py adds PresharedKey to wg1.conf [Peer] only when
            # public_key is present in settings.json). Pure legacy members
            # (no wg_public_key) get the historical, PSK-less config.
            psk_line = ""
            if rec.wg_public_key and rec.wg_preshared_key:
                psk_line = f"PresharedKey = {rec.wg_preshared_key.strip()}\n"
            rec.wg_config = (
                f"[Interface]\n"
                f"Address = {rec.ip_address}/{prefix}\n"
                f"PrivateKey = {rec.wg_private_key.strip()}\n"
                f"\n"
                f"[Peer]\n"
                f"PublicKey = {rec.site_id.wg_server_public_key.strip()}\n"
                f"{psk_line}"
                f"Endpoint = {rec.site_id.remote}:{port}\n"
                f"AllowedIPs = {allowed}\n"
                f"PersistentKeepalive = 25"
            )

    def generate_wg_deploy_link(self):
        self.ensure_one()
        self.wg_deploy_hash = self._generate_temp_hash()
        expiration_minutes = int(
            self.env["ir.config_parameter"].get_param(
                key="ovpn.wg_deploy_hash_expiration_time", default=10
            )
        )
        self.wg_deploy_hash_expiry = (
            arrow.utcnow()
            .shift(minutes=expiration_minutes)
            .strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        )
        if not self.wg_private_key:
            self.wg_register_token = str(uuid.uuid4())
            self.wg_register_token_expiry = (
                arrow.utcnow()
                .shift(minutes=30)
                .strftime(DEFAULT_SERVER_DATETIME_FORMAT)
            )

    @api.depends(
        "wg_config",
        "wg_private_key",
        "wg_register_token",
        "wg_preshared_key",
        "use_wstunnel",
        "site_id.wstunnel_host",
        "site_id.wstunnel_port",
        "site_id.wstunnel_path_prefix",
        "site_id.wstunnel_version",
        "site_id.wg_server_port",
        "site_id.wg_server_public_key",
        "site_id.wg_interface_name",
    )
    def _compute_install_script_preview(self):
        for rec in self:
            try:
                if rec.wg_private_key and rec.wg_config:
                    rec.install_script_preview = rec._build_install_script()
                elif rec.wg_register_token:
                    rec.install_script_preview = rec._build_provisioning_script()
                else:
                    rec.install_script_preview = False
            except Exception:
                rec.install_script_preview = False

    def _build_install_script(self):
        self.ensure_one()
        if not self.wg_config:
            raise UserError(_("Member %s has no WireGuard config yet.") % self.name)
        iface = self.site_id.wg_interface_name or "zebroo"
        config = self.wg_config.strip()
        vpn_ip = self.ip_address
        # Port comes from the stored config (matches what the server actually listens on),
        # not site.wg_server_port which can drift.
        port = self._wg_endpoint_port(config)
        if self.use_wstunnel:
            config = self._endpoint_to_localhost(config, port)

        wg_install = f"""# --- WireGuard install ---
case "$OS" in
Linux)
    if grep -qi 'buster' /etc/os-release 2>/dev/null; then
        cat > /etc/apt/sources.list << 'APT_EOF'
deb http://archive.debian.org/debian buster main contrib non-free
deb http://archive.debian.org/debian buster-backports main contrib non-free
APT_EOF
        apt-get -o Acquire::Check-Valid-Until=false update -qq
        apt-get install -y -t buster-backports wireguard-tools || apt-get install -y wireguard-tools
    else
        apt-get install -y wireguard wireguard-tools
    fi
    ;;
Darwin)
    if ! command -v wg-quick >/dev/null 2>&1; then
        if command -v brew >/dev/null 2>&1; then
            brew install wireguard-tools
        else
            echo "macOS: install Homebrew + 'brew install wireguard-tools' (or WireGuard.app) before running this script." >&2
            exit 1
        fi
    fi
    ;;
esac

WG_DIR=/etc/wireguard
[ "$OS" = "Darwin" ] && WG_DIR=/usr/local/etc/wireguard
mkdir -p "$WG_DIR"
cat > "$WG_DIR/{iface}.conf" << 'WG_CONFIG_EOF'
{config}
WG_CONFIG_EOF
chmod 600 "$WG_DIR/{iface}.conf"

[ "$OS" = "Linux" ] && (modprobe wireguard 2>/dev/null || true)
wg-quick down {iface} 2>/dev/null || true
wg-quick up {iface}

# Enable at boot
if [ "$OS" = "Linux" ]; then
    if command -v systemctl > /dev/null 2>&1 && systemctl is-system-running > /dev/null 2>&1; then
        systemctl enable wg-quick@{iface}
    else
        if ! grep -q "auto {iface}" /etc/network/interfaces 2>/dev/null; then
            printf '\\nauto {iface}\\niface {iface} inet manual\\n    pre-up wg-quick up {iface}\\n    post-down wg-quick down {iface}\\n' >> /etc/network/interfaces
        fi
    fi
fi

echo "WireGuard '{iface}' installed. VPN IP: {vpn_ip}"
echo
echo "===== {iface}.conf (copy this into Synology / WireGuard app etc.) ====="
cat "$WG_DIR/{iface}.conf"
echo "===== end of config ====="
"""

        if not self.use_wstunnel:
            return f"""#!/bin/bash
set -e
OS=$(uname -s)
{wg_install}"""

        # wstunnel branch — compose URL from site fields
        endpoint, prefix, version = self._wstunnel_params()
        return f"""#!/bin/bash
set -e
OS=$(uname -s); ARCH=$(uname -m)

# --- wstunnel install ---
case "$OS-$ARCH" in
  Linux-x86_64)              ASSET_PAT='linux.*(amd64|x86_64)' ;;
  Linux-aarch64|Linux-arm64) ASSET_PAT='linux.*(arm64|aarch64)' ;;
  Darwin-x86_64)             ASSET_PAT='(darwin|macos).*(amd64|x86_64)' ;;
  Darwin-arm64)              ASSET_PAT='(darwin|macos).*arm64' ;;
  *) echo "Unsupported OS/arch for wstunnel: $OS-$ARCH" >&2; exit 1 ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  if [ "$OS" = "Linux" ]; then apt-get install -y curl; fi
fi

TMPDIR=$(mktemp -d)
ASSET_URL=$(curl -fsSL "https://api.github.com/repos/erebe/wstunnel/releases/tags/{version}" \\
  | grep browser_download_url \\
  | grep -E "$ASSET_PAT" \\
  | grep -Ev '\\.sha256|\\.asc' \\
  | grep -E '\\.tar\\.gz' \\
  | head -1 \\
  | sed -E 's/.*"(https[^"]+)".*/\\1/')
if [ -z "$ASSET_URL" ]; then
  echo "wstunnel asset not found for $OS-$ARCH @ {version}" >&2
  exit 1
fi
echo "==> Downloading wstunnel from $ASSET_URL"
curl -fsSL "$ASSET_URL" -o "$TMPDIR/ws.tar.gz"
tar -xzf "$TMPDIR/ws.tar.gz" -C "$TMPDIR"
WS_BIN=$(find "$TMPDIR" -name wstunnel -type f | head -1)
[ -z "$WS_BIN" ] && {{ echo "wstunnel binary not found in archive" >&2; exit 1; }}
install -m 755 "$WS_BIN" /usr/local/bin/wstunnel
rm -rf "$TMPDIR"
/usr/local/bin/wstunnel --version || true

# --- wstunnel service ---
if [ "$OS" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
  cat > /etc/systemd/system/wstunnel-{iface}.service << 'UNIT_EOF'
[Unit]
Description=wstunnel client (WireGuard {iface} over WSS)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/wstunnel client --connection-min-idle 5 -P {prefix} -L udp://{port}:127.0.0.1:{port}?timeout_sec=0 {endpoint}
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/wstunnel-{iface}.log
StandardError=append:/var/log/wstunnel-{iface}.log

[Install]
WantedBy=multi-user.target
UNIT_EOF
  systemctl daemon-reload
  systemctl enable --now wstunnel-{iface}.service
elif [ "$OS" = "Linux" ] && [ -d /etc/init.d ]; then
  # SysV init fallback (no systemd)
  cat > /etc/init.d/wstunnel-{iface} << 'SYSV_EOF'
#!/bin/sh
### BEGIN INIT INFO
# Provides:          wstunnel-{iface}
# Required-Start:    $network $remote_fs
# Required-Stop:     $network $remote_fs
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: wstunnel client (WireGuard {iface} over WSS)
### END INIT INFO

NAME=wstunnel-{iface}
DAEMON=/usr/local/bin/wstunnel
PIDFILE=/var/run/$NAME.pid
LOG=/var/log/$NAME.log
ARGS="client --connection-min-idle 5 -P {prefix} -L udp://{port}:127.0.0.1:{port}?timeout_sec=0 {endpoint}"

start() {{
    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        echo "$NAME already running (pid $(cat $PIDFILE))"
        return 0
    fi
    nohup $DAEMON $ARGS >> $LOG 2>&1 &
    echo $! > $PIDFILE
    sleep 1
    if kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        echo "$NAME started (pid $(cat $PIDFILE))"
    else
        echo "$NAME failed to start; see $LOG"
        return 1
    fi
}}

stop() {{
    if [ -f "$PIDFILE" ]; then
        kill $(cat "$PIDFILE") 2>/dev/null
        rm -f "$PIDFILE"
        echo "$NAME stopped"
    fi
}}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)
        if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
            echo "$NAME running (pid $(cat $PIDFILE))"
        else
            echo "$NAME not running"; exit 1
        fi ;;
    *) echo "Usage: $0 {{start|stop|restart|status}}"; exit 1 ;;
esac
SYSV_EOF
  chmod +x /etc/init.d/wstunnel-{iface}
  if command -v update-rc.d >/dev/null 2>&1; then
    update-rc.d wstunnel-{iface} defaults
  elif command -v chkconfig >/dev/null 2>&1; then
    chkconfig --add wstunnel-{iface}
  fi
  /etc/init.d/wstunnel-{iface} restart
elif [ "$OS" = "Darwin" ]; then
  PLIST=/Library/LaunchDaemons/de.zebroo.wstunnel-{iface}.plist
  cat > "$PLIST" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>de.zebroo.wstunnel-{iface}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/wstunnel</string><string>client</string>
    <string>--connection-min-idle</string><string>5</string>
    <string>-P</string><string>{prefix}</string>
    <string>-L</string><string>udp://{port}:127.0.0.1:{port}?timeout_sec=0</string>
    <string>{endpoint}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/wstunnel-{iface}.log</string>
  <key>StandardErrorPath</key><string>/var/log/wstunnel-{iface}.log</string>
</dict></plist>
PLIST_EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
fi

# Wait until wstunnel listens on local UDP port {port}
for i in 1 2 3 4 5 6 7 8 9 10; do
  if (command -v ss   >/dev/null 2>&1 && ss   -ulnp 2>/dev/null | grep -q ":{port} ") \\
  || (command -v lsof >/dev/null 2>&1 && lsof -nP -iUDP:{port} 2>/dev/null | grep -qi wstunnel); then
    break
  fi
  sleep 1
done

{wg_install}"""

    def _build_provisioning_script(self, use_wstunnel=None):
        self.ensure_one()
        # use_wstunnel=None -> fall back to the member's stored flag; the TCP
        # download button passes True to force the WSS/443 (wstunnel) variant.
        use_wst = self.use_wstunnel if use_wstunnel is None else use_wstunnel
        site = self.site_id
        if not site.wg_server_public_key:
            raise UserError(
                _("Site %s has no WireGuard server public key.") % site.name
            )
        if not self.wg_preshared_key:
            raise UserError(_("Member %s has no preshared key.") % self.name)
        if not self.wg_register_token:
            raise UserError(
                _(
                    "Member %s has no register token. "
                    "Click 'WireGuard Deploy Link' first."
                )
                % self.name
            )
        if not self.ip_address:
            raise UserError(_("Member %s has no IP address.") % self.name)

        iface = site.wg_interface_name or "zebroo"
        prefix = site.netmask_int or 32
        allowed = site.wg_allowed_ips or "10.222.0.0/22"
        port = site.wg_server_port or 51820
        server_pub = site.wg_server_public_key.strip()
        psk = self.wg_preshared_key.strip()
        ip = self.ip_address
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url", default="")
        )
        register_url = f"{base_url}/vpn/register-pubkey/{self.wg_register_token}"

        if use_wst:
            endpoint = f"127.0.0.1:{port}"
        else:
            endpoint = f"{site.remote}:{port}"

        wg_pkg = f"""# --- WireGuard install ---
case "$OS" in
Linux)
    if grep -qi 'buster' /etc/os-release 2>/dev/null; then
        cat > /etc/apt/sources.list << 'APT_EOF'
deb http://archive.debian.org/debian buster main contrib non-free
deb http://archive.debian.org/debian buster-backports main contrib non-free
APT_EOF
        apt-get -o Acquire::Check-Valid-Until=false update -qq
        apt-get install -y -t buster-backports wireguard-tools || apt-get install -y wireguard-tools
    else
        apt-get install -y wireguard wireguard-tools curl
    fi
    ;;
Darwin)
    if ! command -v wg-quick >/dev/null 2>&1; then
        if command -v brew >/dev/null 2>&1; then
            brew install wireguard-tools
        else
            echo "macOS: install Homebrew + 'brew install wireguard-tools' (or WireGuard.app) before running this script." >&2
            exit 1
        fi
    fi
    ;;
esac
"""

        provision = f"""# --- Generate keypair locally (PrivateKey never leaves this host) ---
WG_DIR=/etc/wireguard
[ "$OS" = "Darwin" ] && WG_DIR=/usr/local/etc/wireguard
mkdir -p "$WG_DIR"
umask 077

PRIV=$(wg genkey)
PUB=$(echo "$PRIV" | wg pubkey)
echo "$PRIV" > "$WG_DIR/{iface}.key"
chmod 600 "$WG_DIR/{iface}.key"
echo "==> Generated keypair; public key: $PUB"

# --- Register public key with Odoo (PrivateKey stays local) ---
echo "==> Registering public key with Odoo..."
ATTEMPTS=0
until curl -fsS -X POST -H "Content-Type: text/plain" --data-binary "$PUB" "{register_url}"; do
  ATTEMPTS=$((ATTEMPTS+1))
  if [ $ATTEMPTS -ge 3 ]; then
    echo "ERROR: could not register public key with Odoo after $ATTEMPTS attempts" >&2
    exit 1
  fi
  echo "    retry $ATTEMPTS/3..."
  sleep 2
done
echo

# --- Write WireGuard config (PrivateKey injected from shell variable) ---
cat > "$WG_DIR/{iface}.conf" << WG_CONFIG_EOF
[Interface]
Address = {ip}/{prefix}
PrivateKey = $PRIV

[Peer]
PublicKey = {server_pub}
PresharedKey = {psk}
Endpoint = {endpoint}
AllowedIPs = {allowed}
PersistentKeepalive = 25
WG_CONFIG_EOF
chmod 600 "$WG_DIR/{iface}.conf"

[ "$OS" = "Linux" ] && (modprobe wireguard 2>/dev/null || true)
wg-quick down {iface} 2>/dev/null || true
wg-quick up {iface}

# Enable at boot
if [ "$OS" = "Linux" ]; then
    if command -v systemctl > /dev/null 2>&1 && systemctl is-system-running > /dev/null 2>&1; then
        systemctl enable wg-quick@{iface}
    else
        if ! grep -q "auto {iface}" /etc/network/interfaces 2>/dev/null; then
            printf '\\nauto {iface}\\niface {iface} inet manual\\n    pre-up wg-quick up {iface}\\n    post-down wg-quick down {iface}\\n' >> /etc/network/interfaces
        fi
    fi
fi

echo "WireGuard '{iface}' installed. VPN IP: {ip}"
echo
echo "===== {iface}.conf (copy this into Synology / WireGuard app etc.) ====="
cat "$WG_DIR/{iface}.conf"
echo "===== end of config ====="
"""

        if not use_wst:
            return f"""#!/bin/bash
set -e
OS=$(uname -s)
{wg_pkg}
{provision}"""

        ws_endpoint, ws_prefix, version = self._wstunnel_params()
        return f"""#!/bin/bash
set -e
OS=$(uname -s); ARCH=$(uname -m)

# --- wstunnel install ---
case "$OS-$ARCH" in
  Linux-x86_64)              ASSET_PAT='linux.*(amd64|x86_64)' ;;
  Linux-aarch64|Linux-arm64) ASSET_PAT='linux.*(arm64|aarch64)' ;;
  Darwin-x86_64)             ASSET_PAT='(darwin|macos).*(amd64|x86_64)' ;;
  Darwin-arm64)              ASSET_PAT='(darwin|macos).*arm64' ;;
  *) echo "Unsupported OS/arch for wstunnel: $OS-$ARCH" >&2; exit 1 ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  if [ "$OS" = "Linux" ]; then apt-get install -y curl; fi
fi

TMPDIR=$(mktemp -d)
ASSET_URL=$(curl -fsSL "https://api.github.com/repos/erebe/wstunnel/releases/tags/{version}" \\
  | grep browser_download_url \\
  | grep -E "$ASSET_PAT" \\
  | grep -Ev '\\.sha256|\\.asc' \\
  | grep -E '\\.tar\\.gz' \\
  | head -1 \\
  | sed -E 's/.*"(https[^"]+)".*/\\1/')
if [ -z "$ASSET_URL" ]; then
  echo "wstunnel asset not found for $OS-$ARCH @ {version}" >&2
  exit 1
fi
echo "==> Downloading wstunnel from $ASSET_URL"
curl -fsSL "$ASSET_URL" -o "$TMPDIR/ws.tar.gz"
tar -xzf "$TMPDIR/ws.tar.gz" -C "$TMPDIR"
WS_BIN=$(find "$TMPDIR" -name wstunnel -type f | head -1)
[ -z "$WS_BIN" ] && {{ echo "wstunnel binary not found in archive" >&2; exit 1; }}
install -m 755 "$WS_BIN" /usr/local/bin/wstunnel
rm -rf "$TMPDIR"
/usr/local/bin/wstunnel --version || true

# --- wstunnel service ---
if [ "$OS" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
  cat > /etc/systemd/system/wstunnel-{iface}.service << 'UNIT_EOF'
[Unit]
Description=wstunnel client (WireGuard {iface} over WSS)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/wstunnel client --connection-min-idle 5 -P {ws_prefix} -L udp://{port}:127.0.0.1:{port}?timeout_sec=0 {ws_endpoint}
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/wstunnel-{iface}.log
StandardError=append:/var/log/wstunnel-{iface}.log

[Install]
WantedBy=multi-user.target
UNIT_EOF
  systemctl daemon-reload
  systemctl enable --now wstunnel-{iface}.service
elif [ "$OS" = "Linux" ] && [ -d /etc/init.d ]; then
  cat > /etc/init.d/wstunnel-{iface} << 'SYSV_EOF'
#!/bin/sh
### BEGIN INIT INFO
# Provides:          wstunnel-{iface}
# Required-Start:    $network $remote_fs
# Required-Stop:     $network $remote_fs
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: wstunnel client (WireGuard {iface} over WSS)
### END INIT INFO

NAME=wstunnel-{iface}
DAEMON=/usr/local/bin/wstunnel
PIDFILE=/var/run/$NAME.pid
LOG=/var/log/$NAME.log
ARGS="client --connection-min-idle 5 -P {ws_prefix} -L udp://{port}:127.0.0.1:{port}?timeout_sec=0 {ws_endpoint}"

start() {{
    if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        echo "$NAME already running (pid $(cat $PIDFILE))"
        return 0
    fi
    nohup $DAEMON $ARGS >> $LOG 2>&1 &
    echo $! > $PIDFILE
    sleep 1
    if kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        echo "$NAME started (pid $(cat $PIDFILE))"
    else
        echo "$NAME failed to start; see $LOG"
        return 1
    fi
}}

stop() {{
    if [ -f "$PIDFILE" ]; then
        kill $(cat "$PIDFILE") 2>/dev/null
        rm -f "$PIDFILE"
        echo "$NAME stopped"
    fi
}}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)
        if [ -f "$PIDFILE" ] && kill -0 $(cat "$PIDFILE") 2>/dev/null; then
            echo "$NAME running (pid $(cat $PIDFILE))"
        else
            echo "$NAME not running"; exit 1
        fi ;;
    *) echo "Usage: $0 {{start|stop|restart|status}}"; exit 1 ;;
esac
SYSV_EOF
  chmod +x /etc/init.d/wstunnel-{iface}
  if command -v update-rc.d >/dev/null 2>&1; then
    update-rc.d wstunnel-{iface} defaults
  elif command -v chkconfig >/dev/null 2>&1; then
    chkconfig --add wstunnel-{iface}
  fi
  /etc/init.d/wstunnel-{iface} restart
elif [ "$OS" = "Darwin" ]; then
  PLIST=/Library/LaunchDaemons/de.zebroo.wstunnel-{iface}.plist
  cat > "$PLIST" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>de.zebroo.wstunnel-{iface}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/wstunnel</string><string>client</string>
    <string>--connection-min-idle</string><string>5</string>
    <string>-P</string><string>{ws_prefix}</string>
    <string>-L</string><string>udp://{port}:127.0.0.1:{port}?timeout_sec=0</string>
    <string>{ws_endpoint}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/wstunnel-{iface}.log</string>
  <key>StandardErrorPath</key><string>/var/log/wstunnel-{iface}.log</string>
</dict></plist>
PLIST_EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
fi

# Wait until wstunnel listens on local UDP port {port}
for i in 1 2 3 4 5 6 7 8 9 10; do
  if (command -v ss   >/dev/null 2>&1 && ss   -ulnp 2>/dev/null | grep -q ":{port} ") \\
  || (command -v lsof >/dev/null 2>&1 && lsof -nP -iUDP:{port} 2>/dev/null | grep -qi wstunnel); then
    break
  fi
  sleep 1
done

{wg_pkg}
{provision}"""

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
