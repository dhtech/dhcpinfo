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


def test_a_vlan_alone_and_a_vlan_narrowing_another_search():
    sql, values = sql_for('vlan 10')
    assert 'WHERE vlan = %s AND active ORDER BY' in ' '.join(sql.split())
    assert values == (10, 501)
    # the filter next to the box: with a search ...
    sql, values = search_sql(query.parse('laptop'), False, 500, vlan=950)
    assert "hostname ILIKE %s ESCAPE '\\' AND vlan = %s AND active" in ' '.join(sql.split())
    assert values == ('%laptop%', 950, 501)
    # ... and without one: everybody in the VLAN, history included
    sql, values = search_sql(None, True, 500, vlan=950)
    assert 'WHERE vlan = %s ORDER BY' in ' '.join(sql.split()) and ' active ORDER' not in sql.replace('AND active', '')
    assert values == (950, 501)


def test_nothing_to_search_for_is_an_error_not_everything():
    import pytest
    with pytest.raises(ValueError):
        search_sql(None, True, 500)
