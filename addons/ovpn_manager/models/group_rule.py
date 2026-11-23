from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OvpnGroupRule(models.Model):
    """One directed connection a group allows.

    A group without rules opens everything between its members, in both
    directions. As soon as a group has rules, only these connections are
    opened: from one member to another, one protocol, one port. Replies come
    back through the ESTABLISHED,RELATED rule on the server, so the other side
    can answer but never open a connection of its own.
    """

    _name = "ovpn.group.rule"
    _description = "VPN Group Rule"
    _order = "group_id, from_member_id, to_member_id, protocol, port"

    group_id = fields.Many2one(
        "ovpn.group", string="Group", required=True, ondelete="cascade"
    )
    from_member_id = fields.Many2one(
        "ovpn.member",
        string="From",
        required=True,
        ondelete="cascade",
        help="Member that opens the connection.",
    )
    to_member_id = fields.Many2one(
        "ovpn.member",
        string="To",
        required=True,
        ondelete="cascade",
        help="Member that accepts the connection.",
    )
    protocol = fields.Selection(
        [("tcp", "TCP"), ("udp", "UDP")],
        string="Protocol",
        required=True,
        default="tcp",
    )
    port = fields.Integer("Port", required=True)

    _sql_constraints = [
        (
            "rule_uniq",
            "unique(group_id, from_member_id, to_member_id, protocol, port)",
            "This rule already exists in the group.",
        ),
    ]

    def name_get(self):
        return [
            (
                rec.id,
                "%s → %s %s/%s"
                % (
                    rec.from_member_id.name,
                    rec.to_member_id.name,
                    rec.protocol,
                    rec.port,
                ),
            )
            for rec in self
        ]

    @api.constrains("port")
    def _check_port(self):
        for rec in self:
            if not 1 <= rec.port <= 65535:
                raise ValidationError(_("Port %s is out of range.") % rec.port)

    @api.constrains("from_member_id", "to_member_id", "group_id")
    def _check_members(self):
        for rec in self:
            if rec.from_member_id == rec.to_member_id:
                raise ValidationError(_("From and To must be different members."))
            # A rule for somebody outside the group would open a path the
            # group's member list does not show.
            missing = (rec.from_member_id | rec.to_member_id) - rec.group_id.member_ids
            if missing:
                raise ValidationError(
                    _("%s is not a member of group %s.")
                    % (", ".join(missing.mapped("name")), rec.group_id.name)
                )

    def _get_json(self):
        res = []
        for rec in self:
            # Same as for the pairs: an archived member is unknown to the
            # server and must not show up in settings.json.
            if not (rec.from_member_id.active and rec.to_member_id.active):
                continue
            res.append(
                {
                    "group": rec.group_id.name,
                    "from": rec.from_member_id.name,
                    "to": rec.to_member_id.name,
                    "proto": rec.protocol,
                    "port": rec.port,
                }
            )
        return res
