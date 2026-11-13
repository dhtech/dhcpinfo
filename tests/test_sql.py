# SPDX-License-Identifier: GPL-3.0-or-later
"""The statements the searches become (no database needed)."""
from dhcpinfo import query
from dhcpinfo.db import search_sql


def sql_for(text, history=False, limit=500):
    return search_sql(query.parse(text), history, limit)


def test_each_kind_of_search_has_its_condition():
    for text, condition, value in [
        ('192.0.2.57', 'ip = %s::inet', '192.0.2.57'),
        ('192.0.2.0/24', 'ip <<= %s::cidr', '192.0.2.0/24'),
        ('0000.5e00.5301', 'mac = %s::macaddr', '00:00:5e:00:53:01'),
        ('00:00:5e', 'mac::text LIKE %s', '00:00:5e%'),
        ('laptop', 'hostname ILIKE %s', '%laptop%'),
    ]:
        sql, values = sql_for(text)
        assert condition in sql
        assert values == (value, 501)        # one more than the limit: "there is more"
        assert ' AND active' in sql          # by default only who has it now


def test_history_leaves_the_condition_out():
    sql, _ = sql_for('192.0.2.57', history=True)
    assert ' AND active' not in sql
    assert 'ORDER BY active DESC, starts DESC' in sql


def test_what_was_typed_never_becomes_part_of_the_statement():
    nasty = "x'; DROP TABLE leases; --"
    sql, values = sql_for(nasty)
    assert 'DROP' not in sql and nasty not in sql
    assert values[0] == '%' + nasty + '%'
    # and a name's own wildcards are escaped
    assert sql_for('100%_')[1][0] == '%100\\%\\_%'
