# SPDX-License-Identifier: GPL-3.0-or-later
"""The questions asked of the lease database.

The tables and views are lease2db's (https://github.com/dhtech/lease2db,
schema version 2 or later); this program only reads them. Every
connection is made read-only, so even a mistake here cannot change the
history.
"""
from __future__ import annotations

from . import query as q

SCHEMA_NEEDED = 2

LEASE_COLUMNS = ('ip', 'mac', 'hostname', 'scope', 'vlan', 'network', 'first_seen', 'starts', 'ends',
                 'state', 'active', 'switch', 'port', 'vendor_class')
_SELECT = """
    SELECT host(ip) AS ip, mac::text AS mac, hostname, scope, vlan, network::text AS network,
           first_seen, starts, ends, state, active,
           remote_id_text AS switch, circuit_id_text AS port, vendor_class
    FROM leases_history
    WHERE """
_WHERE = {
    q.IP: 'ip = %s::inet',
    q.NET: 'ip <<= %s::cidr',
    q.MAC: 'mac = %s::macaddr',
    q.MAC_PREFIX: 'mac::text LIKE %s',
    q.NAME: "hostname ILIKE %s ESCAPE '\\'",
    q.VLAN: 'vlan = %s',
}


def search_sql(query: q.Query | None, history: bool, limit: int, vlan: int | None = None) -> tuple[str, tuple]:
    """The statement and its values for QUERY, narrowed to VLAN when
    one is given (QUERY may then be None: everybody in the VLAN). One
    row more than LIMIT is asked for, so the caller can tell that there
    was more."""
    conditions, values = [], []
    if query is not None:
        value: object = query.value
        if query.kind == q.MAC_PREFIX:
            value = query.value + '%'
        elif query.kind == q.NAME:
            value = q.like_pattern(query.value)
        elif query.kind == q.VLAN:
            value = int(query.value)
        conditions.append(_WHERE[query.kind])
        values.append(value)
    if vlan is not None:
        conditions.append(_WHERE[q.VLAN])
        values.append(vlan)
    if not conditions:
        raise ValueError('nothing to search for')
    if not history:
        conditions.append('active')
    # who has it now first, then the latest
    sql = _SELECT + ' AND '.join(conditions) + ' ORDER BY active DESC, starts DESC, ip LIMIT %s'
    return sql, tuple(values) + (limit + 1,)


class Database:
    """A small pool of read-only connections."""

    def __init__(self, dsn: str, pool_size: int = 4):
        # imported here: the rest of the program (and its tests) can be
        # loaded without a PostgreSQL driver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        def configure(conn):
            # every statement is its own transaction, and the SERVER
            # refuses any that writes - whatever this program asks for
            conn.autocommit = True
            conn.execute('SET default_transaction_read_only = on')

        self.pool = ConnectionPool(dsn, min_size=1, max_size=pool_size, open=False, timeout=10,
                                   configure=configure, kwargs={'row_factory': dict_row})
        # open without waiting: the page comes up, and says so, when the
        # database is away
        self.pool.open(wait=False)

    def _rows(self, sql: str, values: tuple = ()) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(sql, values).fetchall()

    def search(self, query: q.Query | None, history: bool, limit: int,
               vlan: int | None = None) -> tuple[list[dict], bool]:
        """(rows, truncated): at most LIMIT leases for QUERY, in VLAN."""
        sql, values = search_sql(query, history, limit, vlan)
        rows = self._rows(sql, values)
        return rows[:limit], len(rows) > limit

    def networks(self) -> list[dict]:
        return self._rows("""
            SELECT network::text AS network, name, vlan, host(gateway) AS gateway,
                   addresses, leases, percent_used
            FROM scopes_usage ORDER BY name, network""")

    def vlans(self) -> list[dict]:
        """The VLANs of the DHCP server's networks, with the names of
        the networks in each - for the VLAN choice in the search form."""
        return self._rows("""
            SELECT vlan, string_agg(DISTINCT nullif(name, ''), ', ' ORDER BY nullif(name, '')) AS names
            FROM scopes WHERE active AND vlan IS NOT NULL
            GROUP BY vlan ORDER BY vlan""")

    def totals(self) -> dict:
        rows = self._rows('SELECT active_leases, active_clients, clients_ever FROM leases_totals')
        return rows[0] if rows else {}

    def schema_version(self) -> int:
        return self._rows('SELECT version FROM lease2db_schema')[0]['version']

    def close(self) -> None:
        self.pool.close()
