from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # Data migration only: nothing on the VPN server changes, so no infra
    # notification either.
    env = api.Environment(cr, SUPERUSER_ID, {"infra_notify_skip": True})
    groups = env["ovpn.group"].with_context(active_test=False).search([])

    # Hubs now have to be members. A hub was never taken from the member
    # list for the pairs (others = members - hubs), so adding it changes
    # nothing in settings.json.
    for group in groups:
        missing = group.hub_member_ids - group.member_ids
        if missing:
            group.member_ids = [(4, member.id) for member in missing]

    # Groups that already have rules keep them enforced: deleting the last
    # rule must not open them fully again.
    groups.filtered("rule_ids").write({"enforce_rules": True})
