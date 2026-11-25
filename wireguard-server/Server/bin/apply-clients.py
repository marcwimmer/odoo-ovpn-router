#!/usr/bin/env python3
"""
Reads settings.json and generates:
  - /data/keys/          : server + per-client WireGuard keypairs (persistent)
  - /etc/wireguard/$IFACE.conf : server config with all peers
  - /data/clients/<name>.conf  : per-client WireGuard configs
  - /data/iptables_rules.sh    : access-control rules using WG_FORWARD chain
"""
import json
import os
import subprocess
from pathlib import Path

settings = json.loads(Path(os.environ["FILE_SETTINGS"]).read_text())
DATA_DIR  = Path(os.environ["FOLDER_DATA"])
KEYS_DIR  = Path(os.environ["FOLDER_KEYS"])
CLIENTS_DIR = Path(os.environ["FOLDER_CLIENTS"])
WG_IFACE  = os.environ.get("WG_IFACE", "wg1")
WG_PORT   = int(os.environ.get("WG_PORT", "51821"))
# TCP MSS forced on SYNs through the tunnel (path MTU 1280 - 40 byte headers)
WG_MSS    = int(os.environ.get("WG_MSS", "1240"))
# Server VPN IP: from env override, else tun0_local from settings.json
WG_SERVER_IP = os.environ.get("WG_SERVER_IP") or settings["tun0_local"]

REMOTE    = settings["remote"]
NET       = settings["net"]
NETMASKINT = settings["netmaskint"]
# WireGuard client network — separate from the OpenVPN NET to avoid route conflicts
WG_NET    = os.environ.get("WG_NET", f"{NET}/{NETMASKINT}")
WG_PREFIX = WG_NET.split("/")[1]  # e.g. "22" from "10.222.0.0/22"


def wg_genkey():
    priv = subprocess.check_output(["wg", "genkey"]).decode().strip()
    pub  = subprocess.check_output(["wg", "pubkey"], input=priv.encode()).decode().strip()
    return priv, pub


def get_or_create_keypair(name: str):
    priv_file = KEYS_DIR / f"{name}.private"
    pub_file  = KEYS_DIR / f"{name}.public"
    if not priv_file.exists():
        priv, pub = wg_genkey()
        priv_file.write_text(priv + "\n")
        pub_file.write_text(pub + "\n")
        priv_file.chmod(0o600)
    return priv_file.read_text().strip(), pub_file.read_text().strip()


def _client_name(value) -> str:
    # settings.json schema: dict {name, email, public_key, preshared_key}
    # Legacy schema was a 2-list [name, email]; kept for safety during rollout.
    if isinstance(value, dict):
        return value["name"]
    return value[0]


def _client_pubkey(value) -> str:
    if isinstance(value, dict):
        return value.get("public_key") or ""
    return ""


def _client_psk(value) -> str:
    if isinstance(value, dict):
        return value.get("preshared_key") or ""
    return ""


def get_ip(name: str) -> str:
    for ip, v in list(settings["clients"].items()) + list(settings["masters"].items()):
        if _client_name(v) == name:
            return ip
    raise Exception(f"Client not found: {name!r}")


def all_clients() -> dict:
    return {**settings["clients"], **settings["masters"]}


def build_iptables_script() -> str:
    """
    Uses a dedicated WG_FORWARD chain so we never flush OpenVPN's rules.
    On reload: just flush WG_FORWARD and re-add.
    """
    lines = [
        "#!/bin/bash",
        "set -e",
        "",
        "# Create or flush our dedicated chain",
        f"iptables -N WG_FORWARD 2>/dev/null || iptables -F WG_FORWARD",
        "# Jump to it from FORWARD (insert at top, idempotent)",
        f"iptables -C FORWARD -j WG_FORWARD 2>/dev/null || iptables -I FORWARD 1 -j WG_FORWARD",
        "",
        "# Uplink-Interface dynamisch ermitteln (war fest auf eth0 verdrahtet)",
        "UPLINK=\"$(ip route show default | awk '{print $5; exit}')\"",
        "# NAT (idempotent check)",
        f"iptables -t nat -C POSTROUTING -s {NET}/{NETMASKINT} -o \"$UPLINK\" -j MASQUERADE 2>/dev/null || \\",
        f"  iptables -t nat -A POSTROUTING -s {NET}/{NETMASKINT} -o \"$UPLINK\" -j MASQUERADE",
        "",
        "# Rueckweg fuer bereits aufgebaute Verbindungen zu den Peers",
        f"iptables -A WG_FORWARD -o {WG_IFACE} -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
        "",
        "# MSS fest klemmen, sonst haengen grosse Downloads (Streaming laeuft kurz",
        "# an und stallt dann), wenn PMTUD unterwegs blockt. --clamp-mss-to-pmtu",
        f"# reicht nicht: es richtet sich nach der MTU von {WG_IFACE} (1420), der Weg",
        "# hinter dem Tunnel ist oft kleiner (Mobilfunk, DS-Lite: Path-MTU 1280).",
        f"# {WG_MSS} = 1280 - 40. Der Kernel erhoeht eine kleinere MSS nie.",
        f"for _dir in -o -i; do",
        f"  while iptables -t mangle -D FORWARD $_dir {WG_IFACE} -p tcp --tcp-flags SYN,RST SYN "
        f"-j TCPMSS --clamp-mss-to-pmtu 2>/dev/null; do :; done",
        f"  iptables -t mangle -C FORWARD $_dir {WG_IFACE} -p tcp --tcp-flags SYN,RST SYN "
        f"-j TCPMSS --set-mss {WG_MSS} 2>/dev/null || \\",
        f"    iptables -t mangle -A FORWARD $_dir {WG_IFACE} -p tcp --tcp-flags SYN,RST SYN "
        f"-j TCPMSS --set-mss {WG_MSS}",
        "done",
        "",
        "# --- Access rules in WG_FORWARD ---",
    ]

    # One template for every ACCEPT between two peers; "match" narrows it
    # down (protocol, port) for directed group rules.
    tmpl = f"iptables -A WG_FORWARD -i {WG_IFACE} -s {{_from}} -d {{_to}}{{match}} -j ACCEPT"

    # masters <-> all clients
    for master_ip in settings["masters"]:
        for client_ip in settings["clients"]:
            lines.append(tmpl.format(_from=master_ip, _to=client_ip, match=""))
            lines.append(tmpl.format(_from=client_ip, _to=master_ip, match=""))

    # custom_routes pairs
    for a_name, b_name in settings["custom_routes"]:
        a_ip = get_ip(a_name)
        b_ip = get_ip(b_name)
        lines.append(tmpl.format(_from=a_ip, _to=b_ip, match=""))
        lines.append(tmpl.format(_from=b_ip, _to=a_ip, match=""))

    # Directed rules of groups that have them: only "from" may open a
    # connection to "to" on this protocol and port. Replies pass through the
    # ESTABLISHED,RELATED rule above, a new connection the other way round
    # falls through to the DROP at the end. Missing key: older settings.json.
    group_rules = settings.get("group_rules") or []
    if group_rules:
        lines.append("")
        lines.append("# --- Group rules (directed) ---")
    for rule in group_rules:
        proto = rule["proto"]
        if proto not in ("tcp", "udp"):
            raise ValueError(f"Unsupported protocol in group rule: {rule!r}")
        port = int(rule["port"])
        lines.append(
            tmpl.format(
                _from=get_ip(rule["from"]),
                _to=get_ip(rule["to"]),
                match=f" -p {proto} --dport {port}",
            )
        )

    # Full-Tunnel: diese Clients duerfen ueber den Server ins Internet raus
    # (im Client muss dazu AllowedIPs = 0.0.0.0/0 stehen)
    internet_clients = settings.get("internet_clients") or []
    if internet_clients:
        lines.append("")
        lines.append("# --- Full-Tunnel (Internet-Ausgang) ---")
    for name in internet_clients:
        lines.append(
            f"iptables -A WG_FORWARD -i {WG_IFACE} -s {get_ip(name)} "
            f"! -d {NET}/{NETMASKINT} -j ACCEPT"
        )

    lines += [
        "",
        f"# Drop everything else from {WG_IFACE} into VPN subnet",
        f"iptables -A WG_FORWARD -i {WG_IFACE} -d {NET}/{NETMASKINT} -j DROP",
    ]

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    KEYS_DIR.mkdir(exist_ok=True, parents=True)
    CLIENTS_DIR.mkdir(exist_ok=True, parents=True)
    Path("/etc/wireguard").mkdir(exist_ok=True, parents=True)

    server_priv, server_pub = get_or_create_keypair("_server")

    # --- /etc/wireguard/<iface>.conf ---
    wg_conf = [
        "[Interface]",
        f"Address = {WG_SERVER_IP}/32",
        f"ListenPort = {WG_PORT}",
        f"PrivateKey = {server_priv}",
        # Don't let wg-quick add static /32 routes for all peers.
        # The route-manager adds them dynamically when a peer actually connects,
        # so non-connected peers fall back to tun0 (OpenVPN).
        "Table = off",
        "",
    ]
    for ip, v in all_clients().items():
        name = _client_name(v)
        client_pub = _client_pubkey(v)
        if client_pub:
            # New flow: client generated its own keypair and registered the pub key
            peer_lines = [f"# {name}", "[Peer]", f"PublicKey = {client_pub}"]
            psk = _client_psk(v)
            if psk:
                peer_lines.append(f"PresharedKey = {psk}")
            peer_lines += [f"AllowedIPs = {ip}/32", ""]
            wg_conf += peer_lines
        else:
            # Legacy: server keeps generating + holding the client's keypair
            _, pub = get_or_create_keypair(name)
            wg_conf += [f"# {name}", "[Peer]", f"PublicKey = {pub}", f"AllowedIPs = {ip}/32", ""]

    conf_path = Path(f"/etc/wireguard/{WG_IFACE}.conf")
    conf_path.write_text("\n".join(wg_conf))
    conf_path.chmod(0o600)
    print(f"Written {conf_path} ({len(all_clients())} peers)")

    # --- per-client configs (legacy members only — new flow keeps the priv key on the client) ---
    legacy_written = 0
    for ip, v in all_clients().items():
        name = _client_name(v)
        if _client_pubkey(v):
            # New flow: client owns the keypair. Don't materialise a server-side conf
            # with a fake/derived PrivateKey — it would be misleading.
            continue
        client_priv, _ = get_or_create_keypair(name)
        # Full-Tunnel-Clients bekommen die Default-Route mit, damit ein frisch
        # heruntergeladenes Profil nicht wieder nur das VPN-Netz routet.
        allowed_ips = (
            "0.0.0.0/0"
            if name in (settings.get("internet_clients") or [])
            else WG_NET
        )
        conf = "\n".join([
            "[Interface]",
            f"Address = {ip}/{WG_PREFIX}",
            f"PrivateKey = {client_priv}",
            "",
            "[Peer]",
            f"PublicKey = {server_pub}",
            f"Endpoint = {REMOTE}:{WG_PORT}",
            f"AllowedIPs = {allowed_ips}",
            "PersistentKeepalive = 25",
            "",
        ])
        p = CLIENTS_DIR / f"{name}.conf"
        p.write_text(conf)
        p.chmod(0o600)
        legacy_written += 1
    print(f"Written {legacy_written} legacy client configs to {CLIENTS_DIR}")

    # --- iptables script ---
    script = build_iptables_script()
    rules_path = DATA_DIR / "iptables_rules.sh"
    rules_path.write_text(script)
    rules_path.chmod(0o755)
    rule_count = script.count("-A WG_FORWARD")
    print(f"Written {rule_count} WG_FORWARD rules to {rules_path}")
