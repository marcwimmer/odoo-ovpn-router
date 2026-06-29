def migrate(cr, version):
    # download_plain_conf was moved entirely to the per-member field
    # deliver_full_conf; drop the now-obsolete site-level column.
    cr.execute("ALTER TABLE ovpn_site DROP COLUMN IF EXISTS download_plain_conf")
