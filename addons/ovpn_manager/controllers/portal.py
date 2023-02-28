from odoo import http, _
import base64
from odoo.http import request, content_disposition
from odoo.osv import expression
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError
from collections import OrderedDict
from odoo.http import request


class PortalAccount(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        if "vpn_count" in counters:
            vpn_count = (
                request.env["ovpn.member"].search_count(self._get_vpn_domain(partner))
                if request.env["ovpn.member"].check_access_rights(
                    "read", raise_exception=False
                )
                else 0
            )
            values["vpn_count"] = vpn_count
        return values

    # ------------------------------------------------------------
    # My VPN
    # ------------------------------------------------------------

    def _get_vpn_domain(self, partner):
        return [("partner_id", "=", partner.id)]

    def _get_vpn_searchbar_sortings(self):
        return {
            "name": {"label": _("Name"), "order": "name desc"},
        }

    def _get_vpn_searchbar_filters(self):
        return {
            "all": {"label": _("All"), "domain": []},
        }

    @http.route(
        ["/my/vpn", "/my/vpn/page/<int:page>"], type="http", auth="user", website=True
    )
    def portal_my_vpn(
        self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw
    ):
        values = self._prepare_my_vpn_values(
            page, date_begin, date_end, sortby, filterby
        )
        # pager
        pager = portal_pager(**values["pager"])
        # content according to pager and archive selected
        vpns = values["vpns"](pager["offset"])
        request.session["my_vpn_history"] = vpns.ids[:100]
        values.update(
            {
                "vpns": vpns,
                "pager": pager,
            }
        )
        return request.render("ovpn_manager.portal_my_vpn", values)

    def _prepare_my_vpn_values(
        self, page, date_begin, date_end, sortby, filterby, domain=None, url="/my/vpn"
    ):
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        VpnMember = request.env["ovpn.member"]
        domain = expression.AND(
            [
                domain or [],
                self._get_vpn_domain(partner),
            ]
        )
        searchbar_sortings = self._get_vpn_searchbar_sortings()
        # default sort by order
        if not sortby:
            sortby = "name"
        order = searchbar_sortings[sortby]["order"]
        searchbar_filters = self._get_vpn_searchbar_filters()
        # default filter by value
        if not filterby:
            filterby = "all"
        domain += searchbar_filters[filterby]["domain"]
        if date_begin and date_end:
            domain += [
                ("create_date", ">", date_begin),
                ("create_date", "<=", date_end),
            ]
        values.update(
            {
                "date": date_begin,
                "vpns": lambda pager_offset: VpnMember.search(
                    domain, order=order, limit=self._items_per_page, offset=pager_offset
                ),
                "page_name": "vpn",
                "pager": {  # vals to define the pager.
                    "url": url,
                    "url_args": {
                        "date_begin": date_begin,
                        "date_end": date_end,
                        "sortby": sortby,
                    },
                    "total": VpnMember.search_count(domain),
                    "page": page,
                    "step": self._items_per_page,
                },
                "default_url": url,
                "searchbar_sortings": searchbar_sortings,
                "sortby": sortby,
                "searchbar_filters": OrderedDict(sorted(searchbar_filters.items())),
                "filterby": filterby,
            }
        )
        return values

    @http.route(["/download/vpn/<int:vpn_id>"], type="http", auth="user", website=True)
    def portal_my_vpn(self, vpn_id, hash=None, **kw):
        member = request.env["ovpn.member"].sudo().browse(vpn_id)
        filename = f"{member.name}.conf"
        document = member._get_content()
        return http.request.make_response(
            base64.b64decode(document),
            headers=[
                ("Content-Type", "application/octet-stream"),
                ("Content-Disposition", content_disposition(filename)),
            ],
        )
