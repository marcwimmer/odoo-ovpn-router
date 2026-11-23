#!/bin/bash
set -e

WG_IFACE="${WG_IFACE:-wg1}"

echo "==> Cleaning up any leftover $WG_IFACE interface..."
wg-quick down "$WG_IFACE" 2>/dev/null || ip link del "$WG_IFACE" 2>/dev/null || true

echo "==> Generating WireGuard config from settings.json..."
python3 "$FOLDER_BIN/apply-clients.py"

echo "==> Starting WireGuard (wg-quick up $WG_IFACE, Table=off)..."
wg-quick up "$WG_IFACE"

echo "==> Applying iptables routing rules (WG_FORWARD chain)..."
bash "$FOLDER_DATA/iptables_rules.sh"

echo "==> Starting route manager (dynamic /32 routes per connected peer)..."
WG_IFACE="$WG_IFACE" bash "$FOLDER_BIN/wg-route-manager.sh" &
ROUTE_MANAGER_PID=$!

echo "==> Applying split DNS..."
python3 "$FOLDER_BIN/apply-dns.py" apply

echo "==> WireGuard running on $WG_IFACE. Watching settings.json for changes..."

# Only the settings wg syncconf cannot change on a live interface. Peer lines
# and comments are left out on purpose, so a peer change never counts here.
iface_hash() {
    awk '/^\[Peer\]/{exit} /^[A-Za-z]/' "/etc/wireguard/$WG_IFACE.conf" | md5sum | cut -d' ' -f1
}

# The route manager only adds and removes routes for peers it still sees.
# A peer that was removed or got a new address would keep its /32 route.
prune_routes() {
    local allowed
    allowed=$(wg show "$WG_IFACE" allowed-ips | tr ' \t' '\n\n' | grep '/32$' | cut -d/ -f1)
    # "ip route" prints host routes without the /32 suffix.
    ip -4 route show dev "$WG_IFACE" | awk '$1 !~ /\// || $1 ~ /\/32$/ {print $1}' | while read -r route; do
        if ! grep -qxF "${route%/32}" <<<"$allowed"; then
            echo "==> Removing stale route $route"
            ip route del "$route" dev "$WG_IFACE" 2>/dev/null || true
        fi
    done
}

full_reload() {
    echo "==> Full reload (all peers reconnect)..."
    kill "$ROUTE_MANAGER_PID" 2>/dev/null || true
    wg-quick down "$WG_IFACE" 2>/dev/null || true
    iptables -F WG_FORWARD 2>/dev/null || true
    python3 "$FOLDER_BIN/apply-clients.py"
    wg-quick up "$WG_IFACE"
    bash "$FOLDER_DATA/iptables_rules.sh"
    WG_IFACE="$WG_IFACE" bash "$FOLDER_BIN/wg-route-manager.sh" &
    ROUTE_MANAGER_PID=$!
}

# Peer changes go through wg syncconf: only added, removed or changed peers are
# touched, every other session keeps running. Falls back to a full reload when
# the interface itself changed or syncconf fails.
peer_reload() {
    local before
    before=$(iface_hash)
    python3 "$FOLDER_BIN/apply-clients.py"
    if [ "$before" != "$(iface_hash)" ]; then
        echo "==> Interface settings changed."
        full_reload
        return
    fi
    if ! wg syncconf "$WG_IFACE" <(wg-quick strip "$WG_IFACE"); then
        echo "==> wg syncconf failed."
        full_reload
        return
    fi
    bash "$FOLDER_DATA/iptables_rules.sh"
    prune_routes
    echo "==> Peers synced, running sessions kept."
}

get_md5() { md5sum "$FILE_SETTINGS" | cut -d' ' -f1; }

_term() {
    echo "==> Shutting down..."
    kill "$ROUTE_MANAGER_PID" 2>/dev/null || true
    [ -f /run/dnsmasq-vpn.pid ] && kill "$(cat /run/dnsmasq-vpn.pid)" 2>/dev/null || true
    wg-quick down "$WG_IFACE" 2>/dev/null || true
    iptables -F WG_FORWARD 2>/dev/null || true
    iptables -D FORWARD -j WG_FORWARD 2>/dev/null || true
    iptables -X WG_FORWARD 2>/dev/null || true
    exit 0
}
trap _term SIGTERM SIGINT

MD5VALUE=$(get_md5)
# Tracked separately so that editing a DNS override does not touch the tunnel
# at all, not even a wg syncconf.
DNS_MD5=$(python3 "$FOLDER_BIN/apply-dns.py" hash)
REST_MD5=$(python3 "$FOLDER_BIN/apply-dns.py" resthash)

while true; do
    sleep 2
    CURRENT=$(get_md5)
    if [ "$MD5VALUE" != "$CURRENT" ]; then
        MD5VALUE=$CURRENT
        CUR_DNS=$(python3 "$FOLDER_BIN/apply-dns.py" hash)
        CUR_REST=$(python3 "$FOLDER_BIN/apply-dns.py" resthash)

        if [ "$DNS_MD5" != "$CUR_DNS" ]; then
            echo "==> DNS overrides changed - reloading dnsmasq..."
            python3 "$FOLDER_BIN/apply-dns.py" apply
            DNS_MD5=$CUR_DNS
        fi

        if [ "$REST_MD5" = "$CUR_REST" ]; then
            echo "==> No peer changes - tunnel left untouched."
            continue
        fi
        REST_MD5=$CUR_REST

        echo "==> settings.json changed - syncing peers..."
        peer_reload
        echo "==> Reload complete."
    fi
done
