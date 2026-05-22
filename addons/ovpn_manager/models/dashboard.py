from odoo import _, api, fields, models


class OvpnDashboard(models.Model):
    _name = "ovpn.dashboard"
    _description = "OVPN Dashboard"

    name = fields.Char()
    member_count = fields.Integer(compute="_compute_counts")
    site_count = fields.Integer(compute="_compute_counts")
    group_count = fields.Integer(compute="_compute_counts")

    def _compute_counts(self):
        Member = self.env["ovpn.member"]
        Site = self.env["ovpn.site"]
        Group = self.env["ovpn.group"]
        for rec in self:
            rec.member_count = Member.search_count([])
            rec.site_count = Site.search_count([])
            rec.group_count = Group.search_count([])

    @api.model
    def _get_singleton(self):
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({"name": "OVPN"})
        return rec

    @api.model
    def _set_as_home_action(self):
        action = self.env.ref(
            "ovpn_manager.ovpn_dashboard_action", raise_if_not_found=False
        )
        if not action:
            return
        users = self.env["res.users"].search([("share", "=", False)])
        users.write({"action_id": action.id})

    @api.model
    def action_open_dashboard(self):
        rec = self._get_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": _("OVPN"),
            "res_model": "ovpn.dashboard",
            "view_mode": "kanban",
            "views": [
                (self.env.ref("ovpn_manager.view_ovpn_dashboard_kanban").id, "kanban")
            ],
            "domain": [("id", "=", rec.id)],
            "target": "current",
        }

    def action_open_members(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "ovpn_manager.members_action"
        )

    def action_open_sites(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "ovpn_manager.ovpn_sites_action"
        )

    def action_open_groups(self):
        return self.env["ir.actions.act_window"]._for_xml_id(
            "ovpn_manager.ovpn_group_action"
        )
