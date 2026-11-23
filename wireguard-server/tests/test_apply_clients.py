"""Tests for the WG_FORWARD rules apply-clients.py writes.

Run: python3 -m unittest discover -s wireguard-server/tests -v
"""

import importlib.util
import json
import os
import re
import shlex
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "Server" / "bin" / "apply-clients.py"
NET = "10.222.0.0/22"

PROXY, APP, ADMIN, LAPTOP = "10.222.0.36", "10.222.0.128", "10.222.0.105", "10.222.0.50"


def base_settings(**extra):
    settings = {
        "remote": "vpn.example.invalid",
        "net": "10.222.0.0",
        "netmaskint": "22",
        "tun0_local": "10.222.0.1",
        "clients": {
            PROXY: {"name": "proxy"},
            APP: {"name": "app"},
            ADMIN: {"name": "admin"},
            LAPTOP: {"name": "laptop"},
        },
        "masters": {},
        "custom_routes": [["laptop", "app"]],
        "internet_clients": ["laptop"],
    }
    settings.update(extra)
    return settings


def load_module(settings):
    """Import apply-clients.py against the given settings, without root."""
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "settings.json"
    path.write_text(json.dumps(settings))
    env = {
        "FILE_SETTINGS": str(path),
        "FOLDER_DATA": tmp.name,
        "FOLDER_KEYS": str(Path(tmp.name) / "keys"),
        "FOLDER_CLIENTS": str(Path(tmp.name) / "clients"),
        "WG_IFACE": "wg1",
        "WG_NET": NET,
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location("apply_clients", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tmp.cleanup()
    return module


def forward_rules(script):
    return [line for line in script.splitlines() if line.startswith("iptables -A WG_FORWARD")]


def verdict(script, src, dst, proto, dport, state="NEW"):
    """First matching WG_FORWARD rule for a packet coming in and leaving on wg1.

    Covers exactly the matches apply-clients.py writes; anything else in a
    rule fails the test instead of being ignored.
    """
    for line in forward_rules(script):
        args = shlex.split(line)[3:]
        match, target, i = True, None, 0
        while i < len(args):
            opt, val = args[i], args[i + 1] if i + 1 < len(args) else None
            if opt in ("-i", "-o"):
                match &= val == "wg1"
            elif opt == "-s":
                match &= val == src
            elif opt == "-d":
                match &= val == dst or (val == NET and dst.startswith("10.222.0."))
            elif opt == "!" and val == "-d":
                match &= not dst.startswith("10.222.0.")
                i += 1
            elif opt == "-p":
                match &= val == proto
            elif opt == "--dport":
                match &= int(val) == dport
            elif opt == "-m" and val == "conntrack":
                i += 2
                match &= state in args[i + 1].split(",")
            elif opt == "-j":
                target = val
            else:
                raise AssertionError(f"unknown match {opt} in {line}")
            i += 2
        if match:
            return target
    return "ACCEPT (falls through)"


class TestWithoutGroupRules(unittest.TestCase):
    def test_missing_key_same_as_empty(self):
        old_style = load_module(base_settings()).build_iptables_script()
        empty = load_module(base_settings(group_rules=[])).build_iptables_script()
        self.assertEqual(old_style, empty)
        self.assertNotIn("--dport", old_style)

    def test_pairs_still_both_directions(self):
        script = load_module(base_settings()).build_iptables_script()
        self.assertEqual(verdict(script, LAPTOP, APP, "tcp", 5432), "ACCEPT")
        self.assertEqual(verdict(script, APP, LAPTOP, "tcp", 5432), "ACCEPT")
        self.assertEqual(verdict(script, PROXY, APP, "tcp", 80), "DROP")


class TestGroupRules(unittest.TestCase):
    RULES = [
        {"group": "hosting", "from": "proxy", "to": "app", "proto": "tcp", "port": 80},
        {"group": "hosting", "from": "proxy", "to": "app", "proto": "tcp", "port": 8100},
        {"group": "hosting", "from": "admin", "to": "app", "proto": "tcp", "port": 22},
    ]

    @classmethod
    def setUpClass(cls):
        cls.script = load_module(base_settings(group_rules=cls.RULES)).build_iptables_script()

    def test_one_accept_per_rule(self):
        self.assertEqual(
            [line for line in forward_rules(self.script) if "--dport" in line],
            [
                f"iptables -A WG_FORWARD -i wg1 -s {PROXY} -d {APP} -p tcp --dport 80 -j ACCEPT",
                f"iptables -A WG_FORWARD -i wg1 -s {PROXY} -d {APP} -p tcp --dport 8100 -j ACCEPT",
                f"iptables -A WG_FORWARD -i wg1 -s {ADMIN} -d {APP} -p tcp --dport 22 -j ACCEPT",
            ],
        )

    def test_allowed_direction(self):
        self.assertEqual(verdict(self.script, PROXY, APP, "tcp", 80), "ACCEPT")
        self.assertEqual(verdict(self.script, PROXY, APP, "tcp", 8100), "ACCEPT")
        self.assertEqual(verdict(self.script, ADMIN, APP, "tcp", 22), "ACCEPT")

    def test_replies_pass(self):
        # The answer of app to admin's SSH session: source port 22, any
        # destination port, but conntrack knows the connection.
        self.assertEqual(
            verdict(self.script, APP, ADMIN, "tcp", 51000, state="ESTABLISHED"), "ACCEPT"
        )

    def test_reverse_direction_dropped(self):
        self.assertEqual(verdict(self.script, APP, ADMIN, "tcp", 22), "DROP")
        self.assertEqual(verdict(self.script, APP, PROXY, "tcp", 80), "DROP")

    def test_other_port_dropped(self):
        self.assertEqual(verdict(self.script, ADMIN, APP, "tcp", 80), "DROP")
        self.assertEqual(verdict(self.script, PROXY, APP, "tcp", 22), "DROP")
        self.assertEqual(verdict(self.script, ADMIN, APP, "udp", 22), "DROP")

    def test_rules_before_drop(self):
        rules = forward_rules(self.script)
        self.assertTrue(rules[-1].endswith(f"-d {NET} -j DROP"))

    def test_unknown_protocol_fails(self):
        module = load_module(
            base_settings(
                group_rules=[{"group": "g", "from": "proxy", "to": "app", "proto": "all", "port": 1}]
            )
        )
        with self.assertRaises(ValueError):
            module.build_iptables_script()

    def test_unknown_member_fails(self):
        module = load_module(
            base_settings(
                group_rules=[{"group": "g", "from": "ghost", "to": "app", "proto": "tcp", "port": 1}]
            )
        )
        with self.assertRaises(Exception):
            module.build_iptables_script()


if __name__ == "__main__":
    unittest.main()
