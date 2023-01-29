from odoo import _, api, fields, models, SUPERUSER_ID
import json
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import ipaddress


class OvpnSite(models.Model):
    _name = "ovpn.site"

    name = fields.Char("Name")

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

    @api.depends("net")
    @api.constrains("net")
    def _compute_netmask(self):
        for rec in self:
            try:
                network = ipaddress.IPv4Network(rec.net)
            except:
                rec.netmask = "n/a"
                rec.netmask_int = 0
            else:
                rec.netmask = str(network.netmask)
                rec.netmask_int = int(rec.net.split("/")[1])

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
            "netmaskint": self.netmask_int,
            "net": self.net,
            "remote_port": self.remote_port,
            "remote": self.remote,
            "custom_routes": (self.group_ids._get_json()),
            "clients": self.member_ids.filtered(lambda x: not x.is_master)._get_json(),
            "masters": self.member_ids.filtered(lambda x: x.is_master)._get_json(),
            "remotes_per_client": remotes_per_client,
            # ????
            "ccdroutes": {"master": []},
        }
        return json.dumps(res, indent=4)
