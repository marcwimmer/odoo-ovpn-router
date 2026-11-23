# WireGuard server

Server part of the VPN: a container that reads `settings.json` (written by the
Odoo module `ovpn_manager`) and turns it into the WireGuard config, the client
configs, the `WG_FORWARD` iptables chain and the split DNS.

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Container definition (host network, `/etc/wg.data` as `/data`) |
| `bin/run.sh` | Build and (re)start the container on the host |
| `Server/bin/run.sh` | Entry point in the container, watches `settings.json` |
| `Server/bin/apply-clients.py` | WireGuard config and `iptables_rules.sh` |
| `Server/bin/apply-dns.py` | dnsmasq config for split DNS |
| `Server/bin/wg-route-manager.sh` | /32 routes for connected peers |

`settings.json` and `.env` stay on the server and are never committed:
`settings.json` holds the peer keys. Copy `.env.example` to `.env`.

## Tests

```sh
python3 -m unittest discover -s wireguard-server/tests -v
```
