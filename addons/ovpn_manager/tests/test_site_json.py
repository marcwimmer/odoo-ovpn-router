# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
import json
import tempfile
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSiteJson(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, infra_notify_skip=True))
        # Never let a test write to the real settings.json default path.
        cls.tmp = tempfile.TemporaryDirectory()
        cls.site = cls.env["ovpn.site"].create(
            {
                "name": "json-site",
                "remote": "vpn.example.invalid",
                "net": "10.222.0.0/16",
                "salt": "test",
                "settings_file_path": str(Path(cls.tmp.name) / "settings.json"),
            }
        )

        def member(name, ip, **vals):
            return cls.env["ovpn.member"].create(
                dict(name=name, site_id=cls.site.id, ip_address=ip, **vals)
            )

        cls.hub = member("hub_a", "10.222.4.1")
        cls.live = member("live_b", "10.222.4.2", full_tunnel=True)
        cls.gone = member("gone_c", "10.222.4.3", full_tunnel=True)
        cls.gone_hub = member("gone_hub_d", "10.222.4.4")
        cls.env["ovpn.group"].create(
            {
                "name": "with-hub",
                "site_id": cls.site.id,
                "member_ids": [(6, 0, (cls.hub | cls.live | cls.gone).ids)],
                "hub_member_ids": [(6, 0, cls.hub.ids)],
            }
        )
        cls.env["ovpn.group"].create(
            {
                "name": "mesh",
                "site_id": cls.site.id,
                "member_ids": [(6, 0, (cls.live | cls.gone | cls.gone_hub).ids)],
                "hub_member_ids": [(6, 0, cls.gone_hub.ids)],
            }
        )
        (cls.gone | cls.gone_hub).active = False

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def _json(self, site):
        return json.loads(site._get_json())

    def _assert_only_active(self, data):
        names = {c["name"] for c in data["clients"].values()}
        self.assertEqual(names, {"hub_a", "live_b"})
        self.assertEqual(data["internet_clients"], ["live_b"])
        routes = {tuple(sorted(r)) for r in data["custom_routes"]}
        # "mesh" lost its only (archived) hub, so the remaining live member
        # has nobody to talk to there.
        self.assertEqual(routes, {("hub_a", "live_b")})

    def test_archived_members_left_out(self):
        self._assert_only_active(self._json(self.site))

    def test_archived_members_left_out_without_active_test(self):
        # Browsing with active_test=False (as done in shell scripts to reach
        # archived records) must not leak them into settings.json.
        site = self.site.with_context(active_test=False)
        self.assertIn(self.gone, site.member_ids)
        self._assert_only_active(self._json(site))
