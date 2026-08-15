from odoo import http, _
import base64
import binascii
import arrow
import logging
import uuid
from odoo.http import request, content_disposition
from odoo.osv import expression
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from collections import OrderedDict
from odoo.http import request

_logger = logging.getLogger(__name__)


class PortalAccount(CustomerPortal):
    @http.route(
        ["/download/byhash/vpn/<hash>"],
        type="http",
        auth="none",
        website=True,
        methods=["GET", "POST"],
    )
    def portal_my_vpn_by_hash(self, hash=None, **kw):
        member = (
            request.env["ovpn.member"].sudo().search([("download_hash", "=", hash)])
        )
        if not member:
            return request.not_found()

        site = member.site_id
        error = None

        if request.httprequest.method == "POST":
            password = kw.get("password", "")
            if site.one_time_password and password == site.one_time_password:
                # TCP/WSS mode (wstunnel over 443) requested via the second button.
                want_tcp = kw.get("config_type") == "tcp"
                # The delivery_mode is authoritative: a member set to
                # "Install-Script (Schlüssel am Client erzeugt)" always gets the
                # keyless provisioning script, even if a legacy server-side
                # wg_private_key is still lingering in the DB. Previously this
                # branched on `not member.wg_private_key`, so a residual legacy
                # key silently forced the server-key path regardless of setting.
                if member.delivery_mode == "script_client_key":
                    if not site.wg_server_public_key or not member.wg_preshared_key:
                        return http.request.make_response(
                            "Member not ready: missing server public key or "
                            "preshared key.\n",
                            status=400,
                            headers=[("Content-Type", "text/plain; charset=utf-8")],
                        )
                    if (
                        not member.wg_register_token
                        or not member.wg_register_token_expiry
                        or member.wg_register_token_expiry < arrow.utcnow().naive
                    ):
                        member.wg_register_token = str(uuid.uuid4())
                        member.wg_register_token_expiry = (
                            arrow.utcnow()
                            .shift(minutes=30)
                            .strftime(DEFAULT_SERVER_DATETIME_FORMAT)
                        )
                    script = member._build_provisioning_script(
                        use_wstunnel=True if want_tcp else None
                    )
                    return http.request.make_response(
                        script,
                        headers=[
                            ("Content-Type", "text/plain; charset=utf-8"),
                            (
                                "Content-Disposition",
                                content_disposition(f"{member.name}.sh"),
                            ),
                        ],
                    )
                # Members with a server-side key (legacy / iPhone): TCP variant is
                # the static .conf with the Endpoint pointed at the local wstunnel.
                if want_tcp and member.wg_config:
                    filename = f"{member.name}-tcp.conf"
                    document = member._get_tcp_content()
                    return http.request.make_response(
                        document,
                        headers=[
                            ("Content-Type", "application/octet-stream"),
                            ("Content-Disposition", content_disposition(filename)),
                        ],
                    )
                if member.delivery_mode == "script_server_key" and member.wg_config:
                    iface = site.wg_interface_name or "zebroo"
                    config = member.wg_config.strip()
                    vpn_ip = member.ip_address
                    script = f"""#!/bin/bash
set -e

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

mkdir -p /etc/wireguard
cat > /etc/wireguard/{iface}.conf << 'WG_CONFIG_EOF'
{config}
WG_CONFIG_EOF
chmod 600 /etc/wireguard/{iface}.conf

modprobe wireguard 2>/dev/null || true
wg-quick down {iface} 2>/dev/null || true
wg-quick up {iface}

if command -v systemctl > /dev/null 2>&1 && systemctl is-system-running > /dev/null 2>&1; then
    systemctl enable wg-quick@{iface}
else
    if ! grep -q "auto {iface}" /etc/network/interfaces 2>/dev/null; then
        printf '\\nauto {iface}\\niface {iface} inet manual\\n    pre-up wg-quick up {iface}\\n    post-down wg-quick down {iface}\\n' >> /etc/network/interfaces
    fi
fi

echo "WireGuard '{iface}' installed. VPN IP: {vpn_ip}"
"""
                    return http.request.make_response(
                        script,
                        headers=[
                            ("Content-Type", "text/plain; charset=utf-8"),
                            (
                                "Content-Disposition",
                                content_disposition(f"{member.name}.sh"),
                            ),
                        ],
                    )
                filename = f"{member.name}.conf"
                document = member._get_content()
                return http.request.make_response(
                    document,
                    headers=[
                        ("Content-Type", "application/octet-stream"),
                        ("Content-Disposition", content_disposition(filename)),
                    ],
                )
            else:
                error = _("Wrong password. Please try again.")

        return request.render(
            "ovpn_manager.vpn_download_password",
            {
                "hash": hash,
                "member_name": member.name,
                "error": error,
                "is_wireguard": bool(member.wg_config),
                # The plain "Download" delivers a Bash install-script (not a .conf)
                # for both script delivery modes; only full_conf ships a .conf.
                # Driven by delivery_mode (authoritative), not by the presence of
                # a lingering legacy wg_private_key.
                "is_script": member.delivery_mode
                in ("script_server_key", "script_client_key"),
                # Client-key members get the provisioning script (_build_provisioning_script),
                # which generates the PrivateKey locally and DOES support macOS
                # (brew + wg genkey). The server-key install-script, on the other
                # hand, is genuinely Linux-only (apt-get/wg-quick). This flag lets
                # the template show the right guide for each case.
                "is_client_key_script": member.delivery_mode == "script_client_key",
                # The TCP/WSS config points the Endpoint at a local wstunnel
                # client, which only gets installed when the member is flagged
                # for wstunnel. Offering the button to everybody handed out
                # configs that can never handshake (Endpoint 127.0.0.1, no
                # wstunnel running), so it follows the flag now.
                "show_tcp": member.use_wstunnel,
            },
        )

    @http.route(
        ["/byemail/<email>"],
        type="http",
        auth="none",
        website=True,
        methods=["GET"],
        csrf=False,
    )
    def vpn_by_email(self, email=None, **kw):
        member = (
            request.env["ovpn.member"]
            .sudo()
            .search([("partner_id.email", "=ilike", email)], limit=1)
        )
        if not member:
            return request.not_found()
        member.download()
        return request.redirect("/download/byhash/vpn/" + member.download_hash)

    @http.route(
        ["/vpn/deploy/<hash>"],
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def deploy_wg(self, hash=None, **kw):
        member = (
            request.env["ovpn.member"].sudo().search([("wg_deploy_hash", "=", hash)])
        )
        if not member:
            return request.not_found()
        if (
            not member.wg_deploy_hash_expiry
            or member.wg_deploy_hash_expiry < arrow.utcnow().naive
        ):
            return request.not_found()

        if member.delivery_mode == "script_client_key":
            if (
                not member.site_id.wg_server_public_key
                or not member.wg_preshared_key
                or not member.wg_register_token
            ):
                return request.not_found()
            script = member._build_provisioning_script()
        else:
            if not member.wg_config:
                return request.not_found()
            script = member._build_install_script()

        member.wg_deploy_hash = False
        member.wg_deploy_hash_expiry = False
        return http.request.make_response(
            script,
            headers=[("Content-Type", "text/plain; charset=utf-8")],
        )

    @http.route(
        ["/vpn/register-pubkey/<token>"],
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def register_pubkey(self, token=None, **kw):
        member = (
            request.env["ovpn.member"]
            .sudo()
            .search([("wg_register_token", "=", token)], limit=1)
        )
        if not member:
            return request.not_found()
        if (
            not member.wg_register_token_expiry
            or member.wg_register_token_expiry < arrow.utcnow().naive
        ):
            return request.not_found()

        raw = request.httprequest.get_data(cache=False, as_text=False) or b""
        if len(raw) > 64:
            return http.request.make_response("invalid public key length\n", status=400)
        pubkey = raw.decode("ascii", errors="replace").strip()
        try:
            decoded = base64.b64decode(pubkey, validate=True)
        except (binascii.Error, ValueError):
            return http.request.make_response("invalid base64\n", status=400)
        if len(decoded) != 32:
            return http.request.make_response(
                "public key must be 32 bytes\n", status=400
            )

        member.wg_public_key = pubkey
        member.wg_register_token = False
        member.wg_register_token_expiry = False
        try:
            member.site_id.generate_json()
        except Exception:
            _logger.exception(
                "register-pubkey: settings.json regeneration failed for member %s",
                member.id,
            )
        return http.request.make_response(
            "OK\n",
            headers=[("Content-Type", "text/plain; charset=utf-8")],
        )

    @http.route(
        ["/vpn/temp/<hash>"],
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def download_vpn_temp(self, hash=None, **kw):
        member = request.env["ovpn.member"].sudo().search([("temp_hash", "=", hash)])
        if not member:
            return request.not_found()

        if (
            not member.temp_hash_expiry
            or member.temp_hash_expiry < arrow.utcnow().naive
        ):
            return request.not_found()

        filename = f"{member.name}.conf"
        document = member._get_content()
        member.temp_hash = False
        member.temp_hash_expiry = False
        return http.request.make_response(
            document,
            headers=[
                ("Content-Type", "application/octet-stream"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
