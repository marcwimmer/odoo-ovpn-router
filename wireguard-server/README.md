# WireGuard server

Server part of the VPN: a container that reads `settings.json` (written by the
Odoo module `ovpn_manager`) and turns it into the WireGuard config, the client
configs, the `WG_FORWARD` iptables chain and the split DNS.

| File | Purpose |
| --- | --- |
| `compose.yml` | Container definition (host network, `/etc/wg.data` as `/data`) |
| `bin/run.sh` | Build and (re)start the container on the host |
| `Server/bin/run.sh` | Entry point in the container, watches `settings.json` |
| `Server/bin/apply-clients.py` | WireGuard config and `iptables_rules.sh` |
| `Server/bin/apply-dns.py` | dnsmasq config for split DNS |
| `Server/bin/wg-route-manager.sh` | /32 routes for connected peers |

`settings.json` and `.env` stay on the server and are never committed:
`settings.json` holds the peer keys. Copy `.env.example` to `.env`.

## Configuration

Host-specific values (data and settings folders, interface, network, project
name) come from `.env` next to `compose.yml`; see `.env.example`. Without
`.env` the defaults in `compose.yml` apply.

The container runs without `privileged`. It gets `NET_ADMIN`, `SYS_MODULE`
and `/dev/net/tun`, which is enough for WireGuard, routes, iptables and
dnsmasq in the host network namespace.

For troubleshooting set `WG_BUILD_TARGET=debug` in `.env` and run
`bin/run.sh`: the debug image adds `nmap` and `tcpdump`. Set it back to
`runtime` (or remove the line) and run `bin/run.sh` again afterwards.

## Live server

The live server builds the container from this folder in its checkout of the
repo. Change the code here (PR), pull it on the server, then run `bin/run.sh`.

## Tests

```sh
python3 -m unittest discover -s wireguard-server/tests -v
# Needs Docker; checks the capabilities and the debug image:
bash wireguard-server/tests/test_capabilities.sh
```

The compose file is named `compose.yml` on purpose: zodoo merges every
`docker-compose*.yml` in the repo into the Odoo project, which would start the
WireGuard container as part of Odoo. `docker compose` finds `compose.yml` on
its own.
