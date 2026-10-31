# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
{
    "assets": {
        "web.assets_backend": [
            "ovpn_manager/static/src/scss/dashboard.scss",
        ],
    },
    "author": "Zebroo GmbH (hello@zebroo.de)",
    "data": [
        "security/groups.xml",
        "security/ir.model.access.csv",
        "data/settings.xml",
        "data/cronjobs.xml",
        "data/infra_notify_cron.xml",
        "views/group_form.xml",
        "views/group_tree.xml",
        "views/member_form.xml",
        "views/member_tree.xml",
        "views/site_form.xml",
        "views/site_tree.xml",
        "views/site_password_mail_views.xml",
        "views/vpn_portal_templates.xml",
        "views/dashboard.xml",
        "views/menu.xml",
        "views/infra_notify_views.xml",
    ],
    "depends": ["base", "portal", "mail"],
    "external_dependencies": {"bin": [], "python": ["jingtrang", "ipaddress", "arrow"]},
    "license": "Other proprietary",
    "name": "ovpn_manager",
    "summary": "Verwaltung von OpenVPN- und WireGuard-Zugängen samt Auslieferung",
    "version": "16.0.1.5.0",
}
