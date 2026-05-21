from odoo import fields, models


class OvpnMemberIpHistory(models.Model):
    _name = "ovpn.member.ip.history"
    _order = "change_date desc"

    member_id = fields.Many2one("ovpn.member", required=True, ondelete="cascade")
    ip_address = fields.Char("IP Address", required=True)
    change_date = fields.Datetime("Changed On", required=True)
