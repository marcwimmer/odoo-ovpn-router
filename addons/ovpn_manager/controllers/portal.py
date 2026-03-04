from odoo import http, _
import base64
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
            },
        )
