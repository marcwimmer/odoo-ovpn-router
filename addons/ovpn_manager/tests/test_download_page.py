# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
import base64
import os
import re

from odoo.modules.module import get_module_resource
from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestDownloadPage(HttpCase):
    """The download page shows only the guide that fits the delivery mode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, infra_notify_skip=True))
        cls.env.user.groups_id |= cls.env.ref("ovpn_manager.group_ovpn_manager")
        cls.site = cls.env["ovpn.site"].create(
            {
                "name": "test-site",
                "remote": "vpn.example.invalid",
                "net": "10.222.0.0/16",
                "salt": "test",
                "settings_file_path": "/tmp/ovpn-test-download-page.json",
                "wg_server_public_key": base64.b64encode(b"\x01" * 32).decode(),
                "wg_interface_name": "testvpn",
                "tun0_local": "10.222.0.1",
            }
        )

    def _page(self, delivery_mode, use_wstunnel=False):
        member = self.env["ovpn.member"].create(
            {
                "name": f"guide_{delivery_mode}_{int(use_wstunnel)}",
                "site_id": self.site.id,
                "ip_address": "10.222.3.%d" % (200 + len(self.site.member_ids)),
                "delivery_mode": delivery_mode,
                "use_wstunnel": use_wstunnel,
                "download_hash": f"hash-{delivery_mode}-{int(use_wstunnel)}",
            }
        )
        response = self.url_open(f"/download/byhash/vpn/{member.download_hash}")
        self.assertEqual(response.status_code, 200)
        return member, response.text

    def _assert_common(self, html):
        self.assertNotIn("myserver.conf", html)
        self.assertIn('data-set="de"', html)
        self.assertIn('data-set="en"', html)
        self.assertIn("Verbindung prüfen", html)
        self.assertIn("Check the connection", html)

    def test_full_conf(self):
        member, html = self._page("full_conf")
        self._assert_common(html)
        self.assertIn('data-mode="full_conf"', html)
        for device in ("mac", "win", "ios", "linux"):
            self.assertIn(f'data-device="{device}"', html)
        self.assertIn(f"{member.name}.conf", html)
        self.assertIn("/etc/wireguard/testvpn.conf", html)
        self.assertIn("ping -c 3 10.222.0.1", html)
        self.assertNotIn('data-device="tcp"', html)
        self.assertNotIn('data-mode="script_', html)

    def test_script_server_key(self):
        member, html = self._page("script_server_key")
        self._assert_common(html)
        self.assertIn('data-mode="script_server_key"', html)
        self.assertIn(f"sudo bash {member.name}.sh", html)
        self.assertIn('data-device="linux"', html)
        for device in ("mac", "win", "ios", "tcp"):
            self.assertNotIn(f'data-device="{device}"', html)

    def test_script_client_key(self):
        member, html = self._page("script_client_key")
        self._assert_common(html)
        self.assertIn('data-mode="script_client_key"', html)
        self.assertIn('data-device="linux"', html)
        self.assertIn('data-device="mac"', html)
        # macOS: the script refuses to run as root.
        self.assertIn(f"bash ~/Downloads/{member.name}.sh", html)
        for device in ("win", "ios", "tcp"):
            self.assertNotIn(f'data-device="{device}"', html)

    def test_full_conf_wstunnel(self):
        member, html = self._page("full_conf", use_wstunnel=True)
        self._assert_common(html)
        self.assertIn('data-device="tcp"', html)
        self.assertIn('value="tcp"', html)
        self.assertIn(f"{member.name}-tcp.conf", html)
        self.assertIn("wstunnel client", html)

    def test_script_server_key_wstunnel(self):
        member, html = self._page("script_server_key", use_wstunnel=True)
        self._assert_common(html)
        self.assertIn('data-device="tcp"', html)
        self.assertIn("wstunnel client", html)

    def test_script_client_key_wstunnel(self):
        _member, html = self._page("script_client_key", use_wstunnel=True)
        self._assert_common(html)
        self.assertIn('data-device="tcp"', html)
        # The TCP script installs wstunnel itself, no manual command.
        self.assertNotIn("wstunnel client --connection", html)

    def test_missing_screenshots_are_hidden(self):
        """Every guide image on the page exists; missing ones are left out."""
        guide_dir = get_module_resource("ovpn_manager", "static", "src", "img", "guide")
        for mode in ("full_conf", "script_server_key", "script_client_key"):
            _member, html = self._page(mode, use_wstunnel=True)
            shots = re.findall(r"/static/src/img/guide/([a-z0-9_]+\.png)", html)
            self.assertTrue(shots, mode)
            for name in shots:
                self.assertTrue(
                    os.path.isfile(os.path.join(guide_dir, name)),
                    f"{mode}: {name} is shown but missing",
                )
