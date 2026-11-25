#!/bin/bash
# Checks that the server image runs with the capabilities from compose.yml
# alone (NET_ADMIN, SYS_MODULE, /dev/net/tun, no --privileged): the server
# brings up WireGuard and its iptables rules, a test peer gets a handshake and
# reaches the server through the tunnel. Also checks that nmap and tcpdump are
# only in the debug image.
#
# Needs Docker with WireGuard support in the kernel. Runs on its own bridge
# network with test keys only; never touches a live server.
#
# Run: bash wireguard-server/tests/test_capabilities.sh
set -euo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
P=wgcaptest
WORK=$(mktemp -d)
CAPS=(--cap-add NET_ADMIN --cap-add SYS_MODULE --device /dev/net/tun)

cleanup() {
    docker rm -f "$P-server" "$P-peer" >/dev/null 2>&1 || true
    docker network rm "$P-net" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "==> Building runtime and debug image"
docker build -q --target runtime -t "$P:runtime" "$DIR/Server" >/dev/null
docker build -q --target debug -t "$P:debug" "$DIR/Server" >/dev/null

for tool in nmap tcpdump; do
    docker run --rm "$P:runtime" sh -c "command -v $tool" >/dev/null \
        && fail "$tool is in the runtime image"
    docker run --rm "$P:debug" sh -c "command -v $tool" >/dev/null \
        || fail "$tool is missing in the debug image"
done
echo "OK: nmap/tcpdump only in the debug image"

PEER_PRIV=$(docker run --rm "$P:runtime" wg genkey)
PEER_PUB=$(docker run --rm -i "$P:runtime" wg pubkey <<<"$PEER_PRIV")

mkdir -p "$WORK/settings" "$WORK/data"
cat >"$WORK/settings/settings.json" <<EOF
{
  "remote": "server.test.invalid",
  "net": "10.99.0.0",
  "netmaskint": "24",
  "tun0_local": "10.99.0.1",
  "clients": {"10.99.0.2": {"name": "peer", "public_key": "$PEER_PUB"}},
  "masters": {},
  "custom_routes": []
}
EOF

docker network create "$P-net" >/dev/null
echo "==> Starting server without --privileged"
docker run -d --name "$P-server" --network "$P-net" "${CAPS[@]}" \
    -v "$WORK/data:/data" -v "$WORK/settings:/root/settings" \
    -e FOLDER_DATA=/data -e FOLDER_KEYS=/data/keys -e FOLDER_CLIENTS=/data/clients \
    -e FILE_SETTINGS=/root/settings/settings.json \
    -e WG_IFACE=wg1 -e WG_NET=10.99.0.0/24 \
    "$P:runtime" /root/bin/run.sh >/dev/null

for _ in $(seq 30); do
    docker logs "$P-server" 2>&1 | grep -q "Watching settings.json" && break
    sleep 1
done
docker logs "$P-server" 2>&1 | grep -q "Watching settings.json" \
    || { docker logs "$P-server"; fail "server did not start"; }
docker exec "$P-server" iptables -S WG_FORWARD >/dev/null \
    || fail "WG_FORWARD chain missing"
echo "OK: server up, WG_FORWARD chain present"

SERVER_PUB=$(docker exec "$P-server" cat /data/keys/_server.public)
SERVER_IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$P-net\").IPAddress}}" "$P-server")

echo "==> Starting test peer"
docker run -d --name "$P-peer" --network "$P-net" "${CAPS[@]}" \
    "$P:runtime" sleep infinity >/dev/null
docker exec -i "$P-peer" sh -c 'cat > /tmp/peer.key' <<<"$PEER_PRIV"
docker exec "$P-peer" sh -c "
    ip link add wg0 type wireguard &&
    wg set wg0 private-key /tmp/peer.key peer $SERVER_PUB \
        endpoint $SERVER_IP:51821 allowed-ips 10.99.0.1/32 persistent-keepalive 1 &&
    ip addr add 10.99.0.2/24 dev wg0 && ip link set wg0 up"

# The server has no route to the peer until wg-route-manager.sh sees the
# handshake and adds the /32 route, so give it a few seconds.
ok=
for _ in $(seq 20); do
    if docker exec "$P-peer" ping -c 1 -W 1 10.99.0.1 >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
done
[ -n "$ok" ] || { docker exec "$P-server" wg show; docker exec "$P-server" ip route; fail "no ping through the tunnel"; }
docker exec "$P-server" wg show wg1 latest-handshakes | awk '$2 > 0' | grep -q . \
    || fail "no handshake on the server"
echo "OK: handshake and ping through the tunnel without --privileged"
