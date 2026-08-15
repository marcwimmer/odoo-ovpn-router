from ipaddress import IPv4Network
from odoo import _, api, fields, models, SUPERUSER_ID
import json
import uuid
from odoo.exceptions import UserError, RedirectWarning, ValidationError
import ipaddress
from pathlib import Path
import random

# Docker-style, typeable password parts: <adjective>_<surname>_<4 digits>
# e.g. "nostalgic_einstein_4217". Easy to read aloud and type, still ~unguessable.
_PWD_ADJECTIVES = [
    "admiring",
    "adoring",
    "agitated",
    "amazing",
    "awesome",
    "blissful",
    "bold",
    "brave",
    "busy",
    "charming",
    "clever",
    "cool",
    "compassionate",
    "confident",
    "cranky",
    "crazy",
    "dazzling",
    "determined",
    "eager",
    "ecstatic",
    "elastic",
    "elated",
    "elegant",
    "epic",
    "exciting",
    "fervent",
    "festive",
    "flamboyant",
    "focused",
    "friendly",
    "frosty",
    "funny",
    "gallant",
    "gifted",
    "goofy",
    "gracious",
    "great",
    "happy",
    "hardcore",
    "heuristic",
    "hopeful",
    "hungry",
    "inspiring",
    "intelligent",
    "jolly",
    "jovial",
    "keen",
    "kind",
    "laughing",
    "loving",
    "lucid",
    "magical",
    "modest",
    "musing",
    "mystifying",
    "naughty",
    "nervous",
    "nice",
    "nifty",
    "nostalgic",
    "optimistic",
    "peaceful",
    "pedantic",
    "pensive",
    "practical",
    "priceless",
    "quirky",
    "quizzical",
    "recursing",
    "relaxed",
    "reverent",
    "romantic",
    "sad",
    "serene",
    "sharp",
    "silly",
    "sleepy",
    "stoic",
    "strange",
    "stupefied",
    "suspicious",
    "sweet",
    "tender",
    "thirsty",
    "trusting",
    "unruffled",
    "upbeat",
    "vibrant",
    "vigilant",
    "vigorous",
    "wizardly",
    "wonderful",
    "xenodochial",
    "youthful",
    "zealous",
    "zen",
]
_PWD_NAMES = [
    "archimedes",
    "babbage",
    "banach",
    "bardeen",
    "bartik",
    "bell",
    "bohr",
    "booth",
    "borg",
    "bose",
    "boyd",
    "brahmagupta",
    "brattain",
    "carson",
    "cartwright",
    "cerf",
    "chandrasekhar",
    "chaplygin",
    "chebyshev",
    "clarke",
    "colden",
    "cori",
    "cray",
    "curie",
    "darwin",
    "davinci",
    "dewdney",
    "dijkstra",
    "dirac",
    "edison",
    "einstein",
    "elion",
    "engelbart",
    "euclid",
    "euler",
    "faraday",
    "fermat",
    "fermi",
    "feynman",
    "franklin",
    "galileo",
    "galois",
    "gates",
    "gauss",
    "goldberg",
    "goldstine",
    "goodall",
    "hamilton",
    "hawking",
    "heisenberg",
    "hermann",
    "herschel",
    "hertz",
    "hodgkin",
    "hofstadter",
    "hoover",
    "hopper",
    "hugle",
    "hypatia",
    "jang",
    "jennings",
    "jepsen",
    "johnson",
    "joliot",
    "jones",
    "kalam",
    "kapitsa",
    "kare",
    "keldysh",
    "kepler",
    "khayyam",
    "kilby",
    "kirch",
    "knuth",
    "kowalevski",
    "lalande",
    "lamarr",
    "lamport",
    "leakey",
    "leavitt",
    "lehmann",
    "lewin",
    "lichterman",
    "liskov",
    "lovelace",
    "lumiere",
    "mahavira",
    "margulis",
    "matsumoto",
    "maxwell",
    "mayer",
    "mccarthy",
    "mcclintock",
    "mclaren",
    "mclean",
    "mcnulty",
    "meitner",
    "mendel",
    "mendeleev",
    "meninsky",
    "merkle",
    "mestorf",
    "mirzakhani",
    "moore",
    "morse",
    "murdock",
    "napier",
    "nash",
    "neumann",
    "newton",
    "nightingale",
    "nobel",
    "noether",
    "northcutt",
    "noyce",
    "panini",
    "pare",
    "pascal",
    "pasteur",
    "payne",
    "perlman",
    "pike",
    "poincare",
    "poitras",
    "ptolemy",
    "raman",
    "ramanujan",
    "ride",
    "ritchie",
    "rosalind",
    "saha",
    "sammet",
    "shannon",
    "shaw",
    "shirley",
    "shockley",
    "sinoussi",
    "snyder",
    "spence",
    "stonebraker",
    "swanson",
    "swartz",
    "swirles",
    "tesla",
    "thompson",
    "torvalds",
    "turing",
    "varahamihira",
    "vaughan",
    "villani",
    "visvesvaraya",
    "volhard",
    "wescoff",
    "wiles",
    "williams",
    "wilson",
    "wing",
    "wozniak",
    "wright",
    "yalow",
    "yonath",
]


def _generate_password():
    """Generate a Docker-style, typeable password."""
    adjective = random.choice(_PWD_ADJECTIVES)
    name = random.choice(_PWD_NAMES)
    number = random.randint(1000, 9999)
    return "%s_%s_%d" % (adjective, name, number)


class OvpnSite(models.Model):
    _name = "ovpn.site"
    _inherit = ["mail.thread"]

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
    password_locked_until = fields.Date(
        "Password locked until",
        help="Optional. While this date is in the future, the automatic password "
        "refresh (cronjob) will NOT change this site's password. Leave empty to "
        "let the cronjob rotate it as usual.",
    )
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
    wg_dns = fields.Char(
        "WireGuard DNS",
        help="Optional. Resolver written as 'DNS = ...' into the client config, "
        "usually the server's own tunnel address (10.222.0.1). Needed to make "
        "the overrides below take effect on clients that cannot carry a hosts "
        "file, e.g. iOS. Beware: WireGuard on iOS/macOS has no split DNS - "
        "while the tunnel is up, *every* lookup of that client goes here, so "
        "the resolver must forward everything else and must stay available. "
        "Leave empty to keep the client's own resolver.",
    )
    wg_dns_upstream = fields.Char(
        "DNS Upstream",
        help="Optional, comma separated. Where the resolver forwards "
        "everything that is not overridden below. Empty means it uses the "
        "server's own /etc/resolv.conf, which is the sane default.",
    )
    dns_record_ids = fields.One2many(
        "ovpn.dns.record", "site_id", string="DNS Overrides"
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
            # Split DNS: the server resolves these names itself instead of
            # letting them go out to the public resolver. Written even when
            # empty, so removing the last record actually clears it on the
            # server side.
            "dns": {
                "listen": self.wg_dns or "",
                "upstream": self.wg_dns_upstream or "",
                "records": self.dns_record_ids._get_json(),
            },
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
        today = fields.Date.context_today(self)
        for site in self.search([]):
            # Respect an optional lock: keep the password until the chosen date.
            if site.password_locked_until and site.password_locked_until >= today:
                continue
            site.one_time_password = _generate_password()

    def action_generate_password(self):
        """Manually (re)generate the password, regardless of the cron lock."""
        for site in self:
            site.one_time_password = _generate_password()

    def action_send_password_mail(self):
        """Open the wizard that mails the current password to chosen recipients."""
        self.ensure_one()
        if not self.one_time_password:
            raise UserError(_("This site has no password yet - generate one first."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Send password by mail"),
            "res_model": "ovpn.site.password.mail",
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context, default_site_id=self.id),
        }

    @api.constrains("net")
    def _check_members(self):
        for member in self.member_ids:
            member._check_ip()
