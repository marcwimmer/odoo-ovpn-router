from odoo import http, _
import base64
import arrow
from odoo.http import request, content_disposition
from odoo.osv import expression
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError
from collections import OrderedDict
from odoo.http import request


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
                if member.wg_config:
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
                        headers=[("Content-Type", "text/plain; charset=utf-8")],
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
            },
        )

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
        if not member or not member.wg_config:
            return request.not_found()
        if (
            not member.wg_deploy_hash_expiry
            or member.wg_deploy_hash_expiry < arrow.utcnow().naive
        ):
            return request.not_found()

        script = member._build_install_script()
        member.wg_deploy_hash = False
        member.wg_deploy_hash_expiry = False
        return http.request.make_response(
            script,
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
