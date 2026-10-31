# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
import base64
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

# Stand-ins for the system tools the installer calls, so the script can run
# in a sandbox. wg-quick logs every call; "wg show" succeeds once "up" ran.
STUBS = {
    "wg-quick": '#!/bin/sh\necho "$@" >> "$STUB_LOG"\n'
    '[ "$1" = up ] && touch "$STUB_STATE/up"\n'
    '[ "$1" = down ] && rm -f "$STUB_STATE/up"\nexit 0\n',
    "wg": '#!/bin/sh\n[ -f "$STUB_STATE/up" ]\n',
    "modprobe": "#!/bin/sh\nexit 0\n",
    "systemctl": "#!/bin/sh\nexit 0\n",
    "apt-get": '#!/bin/sh\necho "apt-get $@" >> "$STUB_LOG"\nexit 0\n',
}


@tagged("post_install", "-at_install")
class TestWgPackage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, infra_notify_skip=True))
        cls.env.user.groups_id |= cls.env.ref("ovpn_manager.group_ovpn_manager")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.site = cls.env["ovpn.site"].create(
            {
                "name": "test-site",
                "remote": "vpn.example.invalid",
                "net": "10.222.0.0/16",
                "salt": "test",
                "settings_file_path": str(cls.root / "settings.json"),
                "wg_server_public_key": base64.b64encode(b"\x01" * 32).decode(),
            }
        )
        cls.member = cls.env["ovpn.member"].create(
            {
                "name": "backup test/1",
                "site_id": cls.site.id,
                "ip_address": "10.222.3.200",
                "delivery_mode": "script_server_key",
            }
        )
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("ovpn.wg_package_dir", str(cls.root / "packages"))
        params.set_param("ovpn.wg_package_host_dir", "/etc/ovpn.data/wg-packages")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        super().tearDownClass()

    def _export(self, member=None):
        member = member or self.member
        member.action_export_wg_package()
        return self.root / "packages" / member._wg_package_name()

    def _server_key_member(self, name, ip):
        return self.env["ovpn.member"].create(
            {
                "name": name,
                "site_id": self.site.id,
                "ip_address": ip,
                "delivery_mode": "script_server_key",
            }
        )

    def test_export_is_root_only_and_reuses_key(self):
        key_before = self.member.wg_private_key
        self.assertTrue(key_before)
        package = self._export()

        self.assertEqual(self.member.wg_private_key, key_before)
        self.assertEqual(stat.S_IMODE(package.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(package.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((package / "install.sh").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((package / "README.txt").stat().st_mode), 0o600)

        script = (package / "install.sh").read_text()
        self.assertIn(key_before, script)
        self.assertIn("--force", script)
        readme = (package / "README.txt").read_text()
        self.assertNotIn(key_before, readme)
        self.assertIn(
            f"/etc/ovpn.data/wg-packages/member-{self.member.id}-backup_test_1", readme
        )

    def test_export_twice_gives_same_files(self):
        package = self._export()
        first = (package / "install.sh").read_bytes()
        self._export()
        self.assertEqual((package / "install.sh").read_bytes(), first)
        self.assertEqual(
            sorted(p.name for p in package.iterdir()), ["README.txt", "install.sh"]
        )

    def test_export_refused_without_server_key(self):
        member = self.env["ovpn.member"].create(
            {
                "name": "client-key",
                "site_id": self.site.id,
                "ip_address": "10.222.3.201",
                "delivery_mode": "script_client_key",
            }
        )
        with self.assertRaises(UserError):
            member.action_export_wg_package()
        self.assertFalse((self.root / "packages" / member._wg_package_name()).exists())

    def test_export_refused_for_wstunnel(self):
        member = self._server_key_member("ws member", "10.222.3.42")
        member.use_wstunnel = True
        with self.assertRaises(UserError):
            member.action_export_wg_package()
        self.assertFalse((self.root / "packages" / member._wg_package_name()).exists())

    def test_package_names_stay_inside_and_unique(self):
        members = [
            self._server_key_member(name, f"10.222.3.{20 + i}")
            for i, name in enumerate([".", "..", "../../etc", "a/b", "a_b", "ä ö"])
        ]
        names = [m._wg_package_name() for m in members]
        self.assertEqual(len(set(names)), len(names))
        packages = self.root / "packages"
        for member in members:
            name = member._wg_package_name()
            self.assertNotIn(".", name)
            self.assertNotIn("/", name)
            package = self._export(member)
            self.assertEqual(package.resolve().parent, packages.resolve())
            self.assertTrue((package / "install.sh").exists())
        # The protected root itself keeps its mode; nothing above it is touched.
        self.assertEqual(stat.S_IMODE(packages.stat().st_mode), 0o700)
        self.assertFalse((self.root / "install.sh").exists())

    def test_symlinked_package_dir_is_refused(self):
        member = self._server_key_member("symlinked", "10.222.3.40")
        packages = self.root / "packages"
        packages.mkdir(mode=0o700, exist_ok=True)
        outside = Path(tempfile.mkdtemp(dir=self.tmp.name))
        (packages / member._wg_package_name()).symlink_to(outside)
        with self.assertRaises(UserError):
            member.action_export_wg_package()
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_at_file_is_replaced_not_followed(self):
        package = self._export()
        victim = Path(tempfile.mkdtemp(dir=self.tmp.name)) / "victim"
        victim.write_text("untouched")
        (package / "install.sh").unlink()
        (package / "install.sh").symlink_to(victim)
        self._export()
        self.assertEqual(victim.read_text(), "untouched")
        self.assertFalse((package / "install.sh").is_symlink())
        self.assertEqual(
            [p.name for p in package.iterdir() if p.name.startswith(".")], []
        )

    def test_user_without_manager_group_cannot_export(self):
        user = self.env["res.users"].create(
            {
                "name": "no vpn manager",
                "login": "no-vpn-manager@example.invalid",
                "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        member = self._server_key_member("no access", "10.222.3.41")
        with self.assertRaises(AccessError):
            member.with_user(user).action_export_wg_package()
        self.assertFalse((self.root / "packages" / member._wg_package_name()).exists())

    def test_regular_install_script_unchanged(self):
        # The deploy-link script keeps its old behaviour (prints the config).
        script = self.member._build_install_script()
        self.assertIn("===== end of config =====", script)
        self.assertNotIn("--force", script)

    def test_installer_can_run_repeatedly(self):
        script = self._export() / "install.sh"
        sandbox = Path(tempfile.mkdtemp(dir=self.tmp.name))
        bin_dir = sandbox / "bin"
        bin_dir.mkdir()
        for name, body in STUBS.items():
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        (sandbox / "state").mkdir()
        wg_dir = sandbox / "wireguard"
        log = sandbox / "calls.log"
        env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            ZEBROO_WG_DIR=str(wg_dir),
            STUB_LOG=str(log),
            STUB_STATE=str(sandbox / "state"),
        )
        conf = wg_dir / "zebroo.conf"
        key = self.member.wg_private_key

        def run(*args):
            return subprocess.run(
                ["bash", str(script), *args],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        first = run()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(conf.read_text().strip(), self.member.wg_config.strip())
        self.assertEqual(stat.S_IMODE(conf.stat().st_mode), 0o600)
        self.assertNotIn(key, first.stdout + first.stderr)
        calls_after_first = log.read_text()

        second = run()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("unverändert", second.stdout)
        self.assertEqual(log.read_text(), calls_after_first)
        self.assertEqual([p.name for p in wg_dir.iterdir()], ["zebroo.conf"])

        conf.write_text("[Interface]\nPrivateKey = something-else\n")
        third = run()
        self.assertEqual(third.returncode, 3)
        self.assertIn("ABBRUCH", third.stderr)
        self.assertIn("something-else", conf.read_text())

        forced = run("--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(conf.read_text().strip(), self.member.wg_config.strip())
        backups = [p for p in wg_dir.iterdir() if ".bak-" in p.name]
        self.assertEqual(len(backups), 1)
        self.assertNotIn(key, forced.stdout + forced.stderr)
