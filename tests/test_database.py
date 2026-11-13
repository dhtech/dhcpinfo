# SPDX-License-Identifier: GPL-3.0-or-later
"""The searches against a real PostgreSQL with lease2db's tables.

Runs when DHCPINFO_TEST_DSN names a database the test may empty and fill
(CI starts one); skipped otherwise.
"""
import os
import pathlib

import pytest

DSN = os.environ.get('DHCPINFO_TEST_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='DHCPINFO_TEST_DSN not set: no database to test against')

SCHEMA = pathlib.Path(__file__).with_name('schema.sql').read_text()
DATA = r"""
INSERT INTO scopes (network, name, vlan, gateway, addresses, active) VALUES
  ('192.0.2.0/24', 'OFFICE', 10, '192.0.2.1', 200, true),
  ('198.51.100.0/24', 'GUESTS', 20, '198.51.100.1', 100, true);
INSERT INTO leases (ip, mac, first_seen, starts, ends, state, current, hostname, circuit_id, remote_id) VALUES
  ('192.0.2.57', '00:00:5e:00:53:01', now() - interval '3 hours', now() - interval '2 hours',
   now() - interval '1 hour', 'active', false, 'old-laptop', convert_to('ge-0/0/7.0:office', 'UTF8'), convert_to('sw-a1', 'UTF8')),
  ('192.0.2.57', '00:00:5e:00:53:02', now() - interval '1 hour', now() - interval '10 minutes',
   now() + interval '50 minutes', 'active', true, 'Anna-PC', '\x00040064010c', '\x0006001ebeef0001'),
  ('192.0.2.58', '00:00:5e:00:53:03', now() - interval '2 hours', now() - interval '2 hours',
   now() - interval '90 minutes', 'released', true, 'phone_100%', NULL, NULL),
  ('198.51.100.9', '00:00:5e:00:53:02', now() - interval '30 minutes', now() - interval '30 minutes',
   NULL, 'active', true, 'Anna-PC', NULL, NULL);
"""


@pytest.fixture(scope='module')
def db():
    import psycopg

    from dhcpinfo.db import Database
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("""DROP VIEW IF EXISTS leases_totals, scopes_usage, leases_active, leases_history;
                        DROP FUNCTION IF EXISTS lease2db_show(bytea);
                        DROP TABLE IF EXISTS leases, scopes, lease2db_schema""")
        conn.execute(SCHEMA)
        conn.execute(DATA)
    database = Database(DSN)
    database.pool.wait(timeout=30)
    yield database
    database.close()


def find(db, text, history=False, limit=500, vlan=None):
    from dhcpinfo import query
    rows, truncated = db.search(query.parse(text), history, limit, vlan)
    return [(r['ip'], r['mac'], r['hostname'], r['active']) for r in rows], truncated


def test_who_has_an_address_now_and_who_had_it(db):
    assert find(db, '192.0.2.57') == ([('192.0.2.57', '00:00:5e:00:53:02', 'Anna-PC', True)], False)
    rows, _ = find(db, '192.0.2.57', history=True)
    # the present holder first, then the one before
    assert rows == [('192.0.2.57', '00:00:5e:00:53:02', 'Anna-PC', True),
                    ('192.0.2.57', '00:00:5e:00:53:01', 'old-laptop', False)]


def test_a_client_a_vendor_a_name_a_network(db):
    assert {r[0] for r in find(db, '0000.5e00.5302')[0]} == {'192.0.2.57', '198.51.100.9'}
    assert len(find(db, '00:00:5e', history=True)[0]) == 4
    assert find(db, 'anna')[0][0][2] == 'Anna-PC'              # case does not matter
    assert find(db, 'old')[0] == []                             # over: not without history
    assert find(db, 'old', history=True)[0][0][2] == 'old-laptop'
    assert {r[0] for r in find(db, '198.51.100.0/24')[0]} == {'198.51.100.9'}
    # a name's own % and _ are searched for, not obeyed
    assert find(db, '100%', history=True)[0][0][2] == 'phone_100%'
    assert find(db, 'phone%100', history=True)[0] == []


def test_vlans(db):
    # a VLAN typed into the box
    assert {r[0] for r in find(db, 'vlan 10')[0]} == {'192.0.2.57'}
    assert {r[0] for r in find(db, 'vlan 10', history=True)[0]} == {'192.0.2.57', '192.0.2.58'}
    # the filter narrowing another search: the client is in two VLANs
    assert {r[0] for r in find(db, '0000.5e00.5302')[0]} == {'192.0.2.57', '198.51.100.9'}
    assert {r[0] for r in find(db, '0000.5e00.5302', vlan=20)[0]} == {'198.51.100.9'}
    # the filter alone
    assert {r[0] for r in find(db, '', vlan=20)[0]} == {'198.51.100.9'}
    assert find(db, '', vlan=999)[0] == []


def test_the_vlans_to_choose_from(db):
    assert db.vlans() == [{'vlan': 10, 'names': 'OFFICE'}, {'vlan': 20, 'names': 'GUESTS'}]


def test_the_limit(db):
    rows, truncated = find(db, '00:00:5e', history=True, limit=2)
    assert len(rows) == 2 and truncated is True


def test_the_row_carries_network_and_where_it_is_plugged_in(db):
    from dhcpinfo import query
    now, before = db.search(query.parse('192.0.2.57'), True, 10)[0]
    assert (now['scope'], now['vlan'], now['network']) == ('OFFICE', 10, '192.0.2.0/24')
    # packed relay information comes out as hex, text as text
    assert (now['switch'], now['port']) == ('00:06:00:1e:be:ef:00:01', '00:04:00:64:01:0c')
    assert (before['switch'], before['port']) == ('sw-a1', 'ge-0/0/7.0:office')
    assert now['ends'].tzinfo is not None


def test_networks_and_totals(db):
    nets = {n['name']: n for n in db.networks()}
    assert nets['OFFICE']['leases'] == 1 and nets['OFFICE']['addresses'] == 200
    assert nets['OFFICE']['gateway'] == '192.0.2.1' and float(nets['OFFICE']['percent_used']) == 0.5
    assert nets['GUESTS']['leases'] == 1
    assert db.totals() == {'active_leases': 2, 'active_clients': 1, 'clients_ever': 3}
    assert db.schema_version() == 2


def test_the_connection_cannot_write(db):
    import psycopg
    with db.pool.connection() as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM leases")


def test_the_pages_on_the_real_database(db):
    from dhcpinfo.app import create_app
    client = create_app(db=db, config={'TIMEZONE': 'UTC'}).test_client()
    text = client.get('/?q=192.0.2.57&history=1').get_data(as_text=True)
    assert '2 leases' in text and 'Anna-PC' in text and 'old-laptop' in text and 'ge-0/0/7.0:office' in text
    assert client.get('/networks').status_code == 200
    assert client.get('/healthz').get_data(as_text=True) == 'ok\n'
    assert client.get('/api/search?q=192.0.2.57').get_json()['leases'][0]['mac'] == '00:00:5e:00:53:02'
