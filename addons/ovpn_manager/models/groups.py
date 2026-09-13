from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import itertools


class OvpnGroups(models.Model):
    _name = "ovpn.group"
    _inherit = ["infra.notify.mixin"]

    # A group is what lets two members reach each other, so its membership
    # is the VPN equivalent of a hostgroup on the SSH side.
    _infra_kind = "VPN-Gruppe"
    _infra_fields = ("name", "member_ids", "site_id")
    _infra_high_fields = ("member_ids",)

    name = fields.Char("Name", required=True)
    member_ids = fields.Many2many("ovpn.member", string="Members")
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)

    def apply_site(self):
        self.ensure_one()
        self.site_id.generate_json()

    def _get_json(self):
        res = []
        for group in self:
            for combo in itertools.combinations(group.member_ids, 2):
                res.append((combo[0].name, combo[1].name))
        return list(set(res))
