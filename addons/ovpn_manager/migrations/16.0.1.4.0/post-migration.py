def migrate(cr, version):
    # The is_master flag handed a member iptables rules to every other peer
    # at once. That access now lives in ovpn.group as a group with hubs, so
    # the column has nothing left to say.
    cr.execute("ALTER TABLE ovpn_member DROP COLUMN IF EXISTS is_master")
