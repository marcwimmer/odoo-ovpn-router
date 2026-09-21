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
    # Hubs turn the group from a mesh into a star: every hub reaches every
    # member, but the members do not reach each other. That is what an
    # admin machine needs - the old is_master flag did the same thing, only
    # globally and without anybody being able to see who is in it.
    hub_member_ids = fields.Many2many(
        "ovpn.member",
        relation="ovpn_group_hub_member_rel",
        column1="group_id",
        column2="member_id",
        string="Hubs",
        help="Leer: jeder erreicht jeden (Vollvermaschung). Sind hier "
        "Mitglieder eingetragen, erreichen nur diese alle anderen der "
        "Gruppe - die uebrigen Mitglieder bleiben untereinander getrennt.",
    )
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)

    def apply_site(self):
        self.ensure_one()
        self.site_id.generate_json()

    def _get_json(self):
        res = []
        for group in self:
            if group.hub_member_ids:
                others = group.member_ids - group.hub_member_ids
                for hub in group.hub_member_ids:
                    for member in others:
                        res.append((hub.name, member.name))
            else:
                for combo in itertools.combinations(group.member_ids, 2):
                    res.append((combo[0].name, combo[1].name))
        return list(set(res))
