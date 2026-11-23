# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
import json
import tempfile
from pathlib import Path

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGroupRules(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, infra_notify_skip=True))
        cls.tmp = tempfile.TemporaryDirectory()
        cls.site = cls.env["ovpn.site"].create(
            {
                "name": "rules-site",
                "remote": "vpn.example.invalid",
                "net": "10.222.0.0/16",
                "salt": "test",
                "settings_file_path": str(Path(cls.tmp.name) / "settings.json"),
            }
        )

        def member(name, ip):
            return cls.env["ovpn.member"].create(
                dict(name=name, site_id=cls.site.id, ip_address=ip)
            )

        cls.proxy = member("proxy_a", "10.222.5.1")
        cls.app = member("app_b", "10.222.5.2")
        cls.admin = member("admin_c", "10.222.5.3")
        cls.other = member("other_d", "10.222.5.4")
        cls.group = cls.env["ovpn.group"].create(
            {
                "name": "hosting",
                "site_id": cls.site.id,
                "member_ids": [(6, 0, (cls.proxy | cls.app | cls.admin).ids)],
            }
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def _json(self):
        return json.loads(self.site._get_json())

    def _rule(self, src, dst, port, protocol="tcp"):
        return self.env["ovpn.group.rule"].create(
            {
                "group_id": self.group.id,
                "from_member_id": src.id,
                "to_member_id": dst.id,
                "protocol": protocol,
                "port": port,
            }
        )

    def test_without_rules_mesh_as_before(self):
        data = self._json()
        routes = {tuple(sorted(r)) for r in data["custom_routes"]}
        self.assertEqual(
            routes,
            {("app_b", "proxy_a"), ("admin_c", "proxy_a"), ("admin_c", "app_b")},
        )
        self.assertEqual(data["group_rules"], [])

    def test_with_rules_only_rules(self):
        self._rule(self.proxy, self.app, 80)
        self._rule(self.proxy, self.app, 8100)
        self._rule(self.admin, self.app, 22)
        data = self._json()
        self.assertEqual(data["custom_routes"], [])
        rules = {
            (r["from"], r["to"], r["proto"], r["port"]) for r in data["group_rules"]
        }
        self.assertEqual(
            rules,
            {
                ("proxy_a", "app_b", "tcp", 80),
                ("proxy_a", "app_b", "tcp", 8100),
                ("admin_c", "app_b", "tcp", 22),
            },
        )

    def test_archived_member_left_out(self):
        self._rule(self.proxy, self.app, 80)
        self._rule(self.admin, self.app, 22)
        self.admin.active = False
        rules = {(r["from"], r["port"]) for r in self._json()["group_rules"]}
        self.assertEqual(rules, {("proxy_a", 80)})

    def test_member_outside_group_rejected(self):
        with self.assertRaises(ValidationError):
            self._rule(self.other, self.app, 22)

    def test_same_member_rejected(self):
        with self.assertRaises(ValidationError):
            self._rule(self.app, self.app, 22)

    def test_port_range(self):
        with self.assertRaises(ValidationError):
            self._rule(self.proxy, self.app, 0)
        with self.assertRaises(ValidationError):
            self._rule(self.proxy, self.app, 70000)
