from odoo import _, api, fields, models, SUPERUSER_ID
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import itertools


class OvpnGroups(models.Model):
    _name = "ovpn.group"
    _inherit = ["infra.notify.mixin"]

    # A group is what lets two members reach each other, so its membership
    # is the VPN equivalent of a hostgroup on the SSH side.
    _infra_kind = "VPN-Gruppe"
    _infra_fields = ("name", "member_ids", "rule_ids", "enforce_rules", "site_id")
    _infra_high_fields = ("member_ids", "rule_ids", "enforce_rules")

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
        domain="[('id', 'in', member_ids)]",
        help="Empty: every member reaches every other member (full mesh). "
        "With hubs, only the hubs reach all other members; the remaining "
        "members stay separated from each other. A hub must be a member of "
        "the group.",
    )
    rule_ids = fields.One2many(
        "ovpn.group.rule",
        "group_id",
        string="Rules",
        help="Empty: all ports in both directions between the members (or "
        "from the hubs). With rules, only these connections are open: from "
        "one member to another, one protocol, one port. The other side may "
        "reply but cannot open a connection of its own. Hubs no longer "
        "matter then.",
    )
    # Without this flag, deleting the last rule silently opens the whole
    # group again (all ports, both directions). With it, a group without
    # rules opens nothing.
    enforce_rules = fields.Boolean(
        "Enforce rules",
        help="Only the rules below open connections. Without any rule the "
        "group opens nothing. Set automatically when a rule is added; clear "
        "it to open the group fully again.",
    )
    site_id = fields.Many2one("ovpn.site", string="Site", required=True)

    @api.constrains("hub_member_ids", "member_ids")
    def _check_hubs_are_members(self):
        # A hub outside the member list reaches every member on all ports,
        # but the group form does not show it as part of the group.
        for group in self:
            missing = group.hub_member_ids - group.member_ids
            if missing:
                raise ValidationError(
                    _("Hubs must be members of group %s: %s")
                    % (group.name, ", ".join(missing.mapped("name")))
                )

    @api.constrains("member_ids")
    def _check_rules_have_members(self):
        # A rule for a member that left the group would stay in the list
        # without any effect. Make the user delete it on purpose.
        for group in self:
            orphaned = group.rule_ids.filtered(
                lambda rule: (rule.from_member_id | rule.to_member_id)
                - group.member_ids
            )
            if orphaned:
                raise ValidationError(
                    _(
                        "Group %s still has rules for members you want to "
                        "remove. Delete these rules first:\n%s"
                    )
                    % (group.name, "\n".join(orphaned.mapped("display_name")))
                )

    def apply_site(self):
        self.ensure_one()
        self.site_id.generate_json()

    def _get_json(self):
        """Pairs that may reach each other on all ports, both directions.

        Groups with rules, or with enforced rules but none left, contribute
        nothing here, see _get_rules_json.
        """
        res = []
        for group in self:
            if group.rule_ids or group.enforce_rules:
                continue
            # Same reason as in ovpn.site._get_json: an archived member must not
            # show up here, the server cannot resolve its name and fails.
            members = group.member_ids.filtered("active")
            hubs = group.hub_member_ids.filtered("active")
            if hubs:
                others = members - hubs
                for hub in hubs:
                    for member in others:
                        res.append((hub.name, member.name))
            else:
                for combo in itertools.combinations(members, 2):
                    res.append((combo[0].name, combo[1].name))
        return list(set(res))

    def _get_rules_json(self):
        return self.rule_ids._get_json()
