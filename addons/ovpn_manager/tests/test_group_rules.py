# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
import importlib.util
import json
import tempfile
from pathlib import Path

from odoo.exceptions import ValidationError
from odoo.modules.module import get_module_path
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

    def _settings(self):
        """settings.json with the pairs in a stable order."""
        data = self._json()
        data["custom_routes"] = sorted(tuple(sorted(r)) for r in data["custom_routes"])
        return data

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

    def test_member_removed_from_group_left_out(self):
        # Removing such a member is blocked now (see below); a rule left over
        # from before that check must still not reach the server.
        self._rule(self.proxy, self.app, 80)
        self._rule(self.admin, self.app, 22)
        self.env.cr.execute(
            "DELETE FROM ovpn_group_ovpn_member_rel "
            "WHERE ovpn_group_id = %s AND ovpn_member_id = %s",
            (self.group.id, self.admin.id),
        )
        self.env.invalidate_all()
        rules = {(r["from"], r["port"]) for r in self._json()["group_rules"]}
        self.assertEqual(rules, {("proxy_a", 80)})

    def test_remove_member_with_rules_blocked(self):
        self._rule(self.proxy, self.app, 80)
        self._rule(self.admin, self.app, 22)
        with self.assertRaises(ValidationError) as caught:
            self.group.member_ids = [(3, self.admin.id)]
        message = str(caught.exception)
        self.assertIn("admin_c → app_b tcp/22", message)
        self.assertNotIn("proxy_a → app_b", message)

    def test_remove_member_without_rules_allowed(self):
        self._rule(self.proxy, self.app, 80)
        self.group.member_ids = [(3, self.admin.id)]
        self.assertNotIn(self.admin, self.group.member_ids)

    def test_rule_sets_enforce_rules(self):
        self.assertFalse(self.group.enforce_rules)
        self._rule(self.proxy, self.app, 80)
        self.assertTrue(self.group.enforce_rules)

    def test_last_rule_deleted_group_stays_closed(self):
        self._rule(self.proxy, self.app, 80).unlink()
        data = self._json()
        self.assertEqual(data["custom_routes"], [])
        self.assertEqual(data["group_rules"], [])

    def test_enforce_rules_cleared_opens_mesh_again(self):
        self._rule(self.proxy, self.app, 80).unlink()
        self.group.enforce_rules = False
        self.assertEqual(len(self._json()["custom_routes"]), 3)

    def test_hub_must_be_member(self):
        with self.assertRaises(ValidationError):
            self.group.hub_member_ids = [(4, self.other.id)]
        self.group.hub_member_ids = [(4, self.admin.id)]
        with self.assertRaises(ValidationError):
            self.group.member_ids = [(3, self.admin.id)]

    def test_hub_domain_offers_members_only(self):
        field = self.env["ovpn.group"]._fields["hub_member_ids"]
        self.assertEqual(field.domain, "[('id', 'in', member_ids)]")

    # Migration 16.0.1.6.0, on data the new constraints would reject.

    def _migrate(self):
        path = Path(get_module_path("ovpn_manager")) / (
            "migrations/16.0.1.6.0/post-migration.py"
        )
        spec = importlib.util.spec_from_file_location("ovpn_mig_1_6", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.env.flush_all()
        module.migrate(self.env.cr, "16.0.1.5.0")
        self.env.invalidate_all()

    def test_hub_outside_members_added_json_unchanged(self):
        # Written past the constraint, like the data from before it.
        self.env.cr.execute(
            "INSERT INTO ovpn_group_hub_member_rel (group_id, member_id) "
            "VALUES (%s, %s)",
            (self.group.id, self.other.id),
        )
        self.env.invalidate_all()
        before = self._settings()
        self.assertIn(("app_b", "other_d"), before["custom_routes"])
        self.assertNotIn(self.other, self.group.member_ids)
        self._migrate()
        self.assertIn(self.other, self.group.member_ids)
        self.assertEqual(self.group.hub_member_ids, self.other)
        self.assertEqual(self._settings(), before)

    def test_groups_with_rules_get_enforce_rules(self):
        self._rule(self.proxy, self.app, 80)
        self.env.cr.execute(
            "UPDATE ovpn_group SET enforce_rules = false WHERE id = %s",
            (self.group.id,),
        )
        plain = self.env["ovpn.group"].create(
            {"name": "plain", "site_id": self.site.id}
        )
        self.env.invalidate_all()
        self._migrate()
        self.assertTrue(self.group.enforce_rules)
        self.assertFalse(plain.enforce_rules)

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
