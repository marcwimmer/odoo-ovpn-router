#!/bin/bash
# Monitors WireGuard peer handshakes and manages /32 host routes.
# - When a peer connects (handshake < 60s ago): add /32 route via $WG_IFACE
#   This overrides the /16 tun0 route, so traffic flows through WireGuard.
# - When a peer goes silent (handshake >= 60s): remove /32 route
#   Traffic falls back to 10.8.0.0/16 dev tun0 (OpenVPN takes over).

WG_IFACE="${WG_IFACE:-wg1}"
HANDSHAKE_TIMEOUT=200  # seconds — WireGuard handshakes happen every ~180s

while true; do
    NOW=$(date +%s)

    # Parse: <pubkey> <allowed_ips>
    declare -A PEER_IPS
    while read -r pubkey allowed; do
        # Take first allowed IP (the /32 client IP), strip the /32
        ip=$(echo "$allowed" | cut -d, -f1 | cut -d/ -f1)
        PEER_IPS["$pubkey"]="$ip"
    done < <(wg show "$WG_IFACE" allowed-ips 2>/dev/null)

    # Parse: <pubkey> <handshake_epoch>
    while read -r pubkey handshake_ts; do
        peer_ip="${PEER_IPS[$pubkey]}"
        [ -z "$peer_ip" ] && continue

        age=$(( NOW - handshake_ts ))

        if [ "$age" -lt "$HANDSHAKE_TIMEOUT" ]; then
            # Connected – ensure /32 route via wg1 (overrides tun0 /16)
            ip route replace "${peer_ip}/32" dev "$WG_IFACE" 2>/dev/null || true
        else
            # Gone – remove /32 route so tun0 handles this IP again
            ip route del "${peer_ip}/32" dev "$WG_IFACE" 2>/dev/null || true
        fi
    done < <(wg show "$WG_IFACE" latest-handshakes 2>/dev/null)

    sleep 5
done
