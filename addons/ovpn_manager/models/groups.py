from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import itertools


class OvpnGroups(models.Model):
    _name = "ovpn.group"

    name = fields.Char("Name", required=True)
    member_ids = fields.Many2many("ovpn.member", string="Members")
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)

    def _get_json(self):
        res = []
        for group in self:
            for combo in itertools.combinations(group.member_ids, 2):
                res.append((combo[0].name, combo[1].name))
        return list(set(res))
