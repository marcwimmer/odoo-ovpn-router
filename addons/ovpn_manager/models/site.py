from ipaddress import IPv4Network
from odoo import _, api, fields, models, SUPERUSER_ID
import json
import uuid
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import ipaddress
from pathlib import Path
import random


class OvpnSite(models.Model):
    _name = "ovpn.site"

    name = fields.Char("Name")

    json_content = fields.Text("JSON Content")
    remote = fields.Char("Public IP Address of Server", required=True)
    remote_port = fields.Integer("Port of Server", default=1194, required=True)
    net = fields.Char("Network", required=True, default="192.180.0.0/16")
    netmask = fields.Char("Netmask", compute="_compute_netmask", store=True)
    netmask_int = fields.Integer("Netmask Int", compute="_compute_netmask", store=True)
    tun0_local = fields.Char("TUN0 Local", default="192.180.0.1")
    tun0_peer = fields.Char("TUN0 peer", default="192.180.0.2")
    ssh_config_prefix = fields.Char("SSH Configs prefix", placeholder="hy-")
    group_ids = fields.One2many("ovpn.group", "site_id", string="Groups")
    member_ids = fields.One2many("ovpn.member", "site_id", string="Members")
    settings_file_path = fields.Char(
        "Settings File Path", default="/etc/settings/settings.json", required=True
    )
    salt = fields.Char("Salt", required=True, help="For hashing the links")
    next_ip = fields.Char()
    next_ip_net = fields.Char()
    one_time_password = fields.Char("One Time Password")
    wg_interface_name = fields.Char(
        "WireGuard Interface Name",
        default="zebroo",
        help="Used as config filename on client: /etc/wireguard/<name>.conf",
    )
    wg_server_public_key = fields.Char("WireGuard Server Public Key")
    wg_server_port = fields.Integer("WireGuard Port", default=51820)
    wg_allowed_ips = fields.Char(
        "WireGuard Allowed IPs", default="10.222.0.0/22,10.8.0.0/16"
    )
    wstunnel_host = fields.Char(
        "wstunnel Host",
        default="vpn.zebroo.de",
        help="Hostname the wstunnel client connects to (must resolve and have a valid TLS cert).",
    )
    wstunnel_port = fields.Integer(
        "wstunnel TCP Port",
        default=443,
        help="TCP port for the WSS connection. Must match what nginx/wstunnel-server listens on.",
    )
    wstunnel_path_prefix = fields.Char(
        "wstunnel Path Prefix",
        default="wgws",
        help="Shared-secret-ish URL prefix in the WS upgrade path. Must match the server's "
        "--restrict-http-upgrade-path-prefix.",
    )
    wstunnel_version = fields.Char(
        "wstunnel Version",
        default="v10.5.5",
        help="Release tag on github.com/erebe/wstunnel used by client install script.",
    )
    download_plain_conf = fields.Boolean(
        "Download Plain Conf",
        help="If enabled, downloads deliver the raw WireGuard .conf file instead "
        "of the install script. Handy for iPhone (WireGuard app imports .conf).",
    )

    def _next_ip(self):
        self.ensure_one()
        if not self.next_ip_net:
            return False

        network = IPv4Network(self.next_ip_net)
        hosts = list(network.hosts())

        if not self.next_ip:
            self.next_ip = str(hosts[0])

        ip = False
        for i, host in enumerate(hosts):
            if str(host) == self.next_ip:
                ip = self.next_ip
                if i + 1 < len(hosts):
                    self.next_ip = str(hosts[i + 1])
                else:
                    raise ValidationError("No more IPs available in network")
                break

        if not ip:
            raise ValidationError("Could not determine next ip")
        return ip

    @api.depends("net")
    @api.constrains("net")
    def _compute_netmask(self):
        for rec in self:
            try:
                network = ipaddress.IPv4Network(rec.net)
            except (ValueError, TypeError):
                rec.netmask = "n/a"
                rec.netmask_int = 0
            else:
                rec.netmask = str(network.netmask)
                rec.netmask_int = int(rec.net.split("/")[1])

    def generate_json(self):
        self.ensure_one()
        data = self._get_json()
        self.json_content = data
        Path(self.settings_file_path).write_text(self.json_content)

    def _get_json(self):
        self.ensure_one()

        remotes_per_client = {}
        for member in self.member_ids.filtered(lambda x: x.force_remote):
            remotes_per_client[member.ip_address] = member.force_remote

        res = {
            "ssh_config_prefix": self.ssh_config_prefix,
            "tun0_local": self.tun0_local,
            "tun0_peer": self.tun0_peer,
            "netmask": self.netmask,
            "netmaskint": str(self.netmask_int),
            "net": self.net.split("/")[0],
            "remote_port": self.remote_port,
            "remote": self.remote,
            "custom_routes": (self.group_ids._get_json()),
            "clients": self.member_ids.filtered(lambda x: not x.is_master)._get_json(),
            "masters": self.member_ids.filtered(lambda x: x.is_master)._get_json(),
            "remotes_per_client": remotes_per_client,
            # ????
            "ccdroutes": {"master": []},
            "create_date": fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return json.dumps(res, indent=4)

    def match_ip(self, ip):
        network = ipaddress.IPv4Network(self.net)
        if ip not in network:
            raise ValidationError(
                _("IP Address %s is not in network %s") % (ip, network)
            )

    @api.model
    def _refresh_one_time_password(self):
        for site in self.search([]):
            site.one_time_password = str(uuid.uuid4())

    @api.constrains("net")
    def _check_members(self):
        for member in self.member_ids:
            member._check_ip()
