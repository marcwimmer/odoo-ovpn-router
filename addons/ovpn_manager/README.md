#1 ovpn_manager

```
{
    "remote": "46.254.140.82",
    "remote_port": "1194",
    "net": "192.180.0.0",
    "netmaskint": "16",
    "netmask": "255.255.0.0",
    "tun0_local": "192.180.0.1",
    "tun0_peer": "192.180.0.2",
    "ssh_config_prefix": "hy-",
    "masters": {
        "192.180.99.1": ["macbook-marc", "marc@itewimmer.de"],
        "192.180.99.2": ["xps-marc", "marc@itewimmer.de"],
        "192.180.99.3": ["ipad-marc", "marc@itewimmer.de"]
    },
    "ccdroutes": {
        "master": [
        ]
    },
    "custom_routes": [
        ["router", "ite-old"],
        ["router", "hetzi1"],
        ["ite-odoo", "ite-old"],

        ["ite-odoo", "david_fleischmann"],

        ["odoodev-ipe", "stefan_prousa"],
        ["odoodev-caetec", "stefan_prousa"],
        ["odoodev-caetec", "copper"],
        ["odoodev-ipe", "copper"],
        ["odoodev-caetec", "calcium"],
        ["odoodev-ipe", "calcium"],
        ["cicd-ipe2", "calcium"],
        ["cicd-ipe2", "copper"],
        ["stefan_prousa", "copper"],

        ["odoodev-swmsolar", "cicd-swm-solar"],
        ["odoodev-swmemob", "cicd-swm-emob"],
        ["odoodev-swmsolar", "david_fleischmann"],
        ["odoodev-swmemob", "david_fleischmann"],
        ["odoodev-rs", "david_fleischmann"],
        ["odoodev-cpb", "cpb_zergling3"],
        ["odoodev-cpb", "andreas_tropschug"],

        ["odoodev-swmsolar", "cicd-swm-emob"],
        ["odoodev-swmsolar", "cicd-swm-solar"],

        ["iordan_pinto", "kraeuterblume"],
        ["iordan_pinto", "odoodev"],
        ["macbook-marc", "xps-marc"],
        ["silverstar", "odoosandbox"],
        ["silverstar", "odoodev"],
        ["sunday_cicd", "odoodev"]
    ],
    "clients": {
        "192.180.0.2": ["ovpn", null],
        "192.180.0.3": ["humphrey", "marc@itewimmer.de"],
        "192.180.0.4": ["hetzi1", "marc@itewimmer.de"],
        "192.180.0.6": ["ite-wikis", "marc@itewimmer.de"],
        "192.180.0.7": ["ite-apps", "marc@itewimmer.de"],
        "192.180.0.8": ["ite-old", "marc@itewimmer.de"],
        "192.180.77.2": ["router", null],
        "192.180.77.4": ["ite", "marc@itewimmer.de"],
        "192.180.77.5": ["odoodev-sunday", "marc@itewimmer.de"],
        "192.180.77.6": ["zabbix", "marc@itewimmer.de"],
        "192.180.77.7": ["cicd-swm-solar", "marc@itewimmer.de"],
        "192.180.77.8": ["cicd-swm-emob", "marc@itewimmer.de"],
        "192.180.77.9": ["odoodev-ipe", "marc@itewimmer.de"],
        "192.180.77.10": ["odoodev-rs", "marc@itewimmer.de"],
        "192.180.77.12": ["odoodev-cpb", "marc@itewimmer.de"],
        "192.180.77.13": ["odoodev-swmsolar", "marc@itewimmer.de"],
        "192.180.77.14": ["cicd-swm", "marc@itewimmer.de"],
        "192.180.77.15": ["odoodev-swmemob", "marc@itewimmer.de"],
        "192.180.77.16": ["ite-odoo", "marc@itewimmer.de"],
        "192.180.77.17": ["cicd-ipe2", "marc@itewimmer.de"],
        "192.180.77.19": ["odoodev-caetec", "marc@itewimmer.de"],
        "192.180.77.24": ["git2", "marc@itewimmer.de"],
        "192.180.77.25": ["kraeuterblume", "marc@itewimmer.de"],
        "192.180.77.26": ["cpsolar", "marc@itewimmer.de"],
        "192.180.77.27": ["odoosandbox", "marc@itewimmer.de"],
        "192.180.77.28": ["odoodev", "marc@itewimmer.de"],
        "192.180.95.1": ["stefan_prousa", "stefan.prousa@ipetronik.com"],
        "192.180.95.2": ["jan_gottschau", "jan.gottschau@sunday.de"],
        "192.180.95.3": ["walter_salzmann", "walter.salzmann@manatec.de"],
        "192.180.95.4": ["david_fleischmann", "david@ib-fleischmann.de"],
        "192.180.95.5": ["marko_miljanovic_sunday_de", "marko.miljanovic@sunday.de"],
        "192.180.95.6": ["cpb_zergling3", "at@at-ose.de"],
        "192.180.95.7": ["sunday_stage", "marc@itewimmer.de"],
        "192.180.95.8": ["copper", "tobias.prousa@ipetronik.com"],
        "192.180.95.9": ["calcium", "stefan.prousa@ipetronik.com"],
        "192.180.95.10": ["raffaele_del_gatto", "raffaele.del.gatto@sunday.de"],
        "192.180.95.11": ["darshan_patel", "darshan.patel@sunday.de"],
        "192.180.95.12": ["khouloud_jlassi", "khouloud.jlassi@sunday.de"],
        "192.180.95.13": ["karthik_pradhan", "karthik.pradhan@sunday.de"],
        "192.180.95.14": ["sasa_stanisljevic", "sasa.stanisljevic@sunday.de"],
        "192.180.95.15": ["iordan_pinto", "pintoiordan@gmail.com"],
        "192.180.95.16": ["andreas_tropschug", "at@at-ose.de"],
        "192.180.95.17": ["silverstar", "jsilverstar19@gmail.com"],
        "192.180.95.18": ["sunday_cicd", "marc@itewimmer.de"]
    },
    "remotes_per_client": {
        "192.180.0.2": "127.0.0.1 1194"
    },
    "alternative_names": {
    }
}
```

#2 Contributors

* Marc Wimmer <marc@itewimmer.de>

