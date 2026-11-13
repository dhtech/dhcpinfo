# SPDX-License-Identifier: GPL-3.0-or-later
"""The pages, with a stand-in for the database."""
import datetime

import pytest

pytest.importorskip('flask')

from dhcpinfo.app import create_app  # noqa: E402

UTC = datetime.timezone.utc


def lease(**over):
    row = {'ip': '192.0.2.57', 'mac': '00:00:5e:00:53:01', 'hostname': 'laptop', 'scope': 'OFFICE',
           'vlan': 10, 'network': '192.0.2.0/24',
           'first_seen': datetime.datetime(2026, 1, 10, 11, 0, tzinfo=UTC),
           'starts': datetime.datetime(2026, 1, 10, 11, 30, tzinfo=UTC),
           'ends': datetime.datetime(2026, 1, 10, 12, 30, tzinfo=UTC),
           'state': 'active', 'active': True, 'switch': 'sw-a1', 'port': 'ge-0/0/7.0:office',
           'vendor_class': None}
    row.update(over)
    return row


class FakeDB:
    def __init__(self, rows=(), truncated=False, broken=False, version=2):
        self.rows, self.truncated, self.broken, self.version = list(rows), truncated, broken, version
        self.asked = []
        self.vlan_list = [{'vlan': 10, 'names': 'OFFICE'}, {'vlan': 20, 'names': 'GUESTS, GUESTS-2'},
                          {'vlan': 30, 'names': None}]

    def _check(self):
        if self.broken:
            raise RuntimeError('connection refused')

    def search(self, query, history, limit, vlan=None):
        self._check()
        asked = (query.kind, query.value, history, limit) if query else (None, None, history, limit)
        self.asked.append(asked + ((vlan,) if vlan is not None else ()))
        return self.rows, self.truncated

    def networks(self):
        self._check()
        return [{'network': '192.0.2.0/24', 'name': 'OFFICE', 'vlan': 10, 'gateway': '192.0.2.1',
                 'addresses': 200, 'leases': 50, 'percent_used': 25.0}]

    def vlans(self):
        self._check()
        return self.vlan_list

    def totals(self):
        self._check()
        return {'active_leases': 1234, 'active_clients': 1200, 'clients_ever': 5000}

    def schema_version(self):
        self._check()
        return self.version


def client(db, **config):
    app = create_app(db=db, config=dict({'TIMEZONE': 'Europe/Stockholm', 'LIMIT': 500}, **config))
    return app.test_client()


def test_the_front_page_is_a_search_box_and_the_totals():
    page = client(FakeDB()).get('/')
    text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert '<input id="q" name="q" type="search"' in text
    assert '1234' in text and '1200' in text and '5000' in text


def test_a_search_shows_the_lease_in_local_time_with_links():
    db = FakeDB([lease()])
    page = client(db).get('/?q=192.0.2.57')
    text = page.get_data(as_text=True)
    assert db.asked == [('ip', '192.0.2.57', False, 500)]
    assert '1 lease' in text and 'for address' in text
    assert '00:00:5e:00:53:01' in text and 'laptop' in text and 'sw-a1' in text
    assert 'ge-0/0/7.0:office' in text and 'OFFICE' in text and 'vlan 10' in text
    # 11:00 UTC is 12:00 in Stockholm in January
    assert '2026-01-10 12:00:00' in text and '2026-01-10 13:30:00' in text
    assert '● active' in text
    # every value leads on: the address, the client, the network
    assert 'href="/?q=192.0.2.57&amp;history=1"' in text
    assert 'href="/?q=00:00:5e:00:53:01&amp;history=1"' in text
    assert 'href="/?q=192.0.2.0/24"' in text


def test_history_and_what_a_finished_lease_looks_like():
    db = FakeDB([lease(active=False, state='released'), lease(active=False, state='active', ends=None)])
    text = client(db).get('/?q=laptop&history=1').get_data(as_text=True)
    assert db.asked == [('name', 'laptop', True, 500)]
    assert 'released' in text
    assert 'ended' in text            # superseded: dhcpd never said more than "active"
    assert 'never' in text            # no end time
    assert '● active' not in text
    # the form remembers where the search was made
    assert 'name="history" value="1" checked' in text
    assert 'name="history" value="0" checked' not in text


def test_current_leases_is_the_default_place_to_search():
    db = FakeDB([lease()])
    text = client(db).get('/?q=laptop&history=0').get_data(as_text=True)
    assert db.asked == [('name', 'laptop', False, 500)]
    assert 'name="history" value="0" checked' in text
    assert 'Current leases' in text and 'History' in text


def test_the_vlan_filter_alone_and_with_a_search():
    db = FakeDB([lease()])
    c = client(db)
    text = c.get('/?vlan=10').get_data(as_text=True)
    assert db.asked == [(None, None, False, 500, 10)]
    assert '1 lease' in text and 'in VLAN' in text
    # the VLAN is chosen from the DHCP server's own, by number and name
    assert '<select id="vlan" name="vlan">' in text
    assert '<option value="10" selected>10 - OFFICE</option>' in text
    assert '<option value="20">20 - GUESTS, GUESTS-2</option>' in text
    assert '<option value="30">30</option>' in text
    assert '<option value="">any</option>' in text
    c.get('/?q=laptop&vlan=950&history=1')
    assert db.asked[-1] == ('name', 'laptop', True, 500, 950)
    # typed into the box, a VLAN is a search of its own
    c.get('/?q=vlan+10')
    assert db.asked[-1] == ('vlan', '10', False, 500)
    # the lease's VLAN leads to everybody in it
    assert 'href="/?vlan=10"' in text
    # a VLAN that is none is explained, and nothing is asked
    before = len(db.asked)
    bad = c.get('/?q=laptop&vlan=banana')
    assert bad.status_code == 400 and '1 to 4094' in bad.get_data(as_text=True) and len(db.asked) == before


def test_the_vlan_choice():
    db = FakeDB([lease()])
    # nothing chosen: "any" is
    text = client(db).get('/').get_data(as_text=True)
    assert '<option value="" selected>any</option>' in text and 'selected>10' not in text
    # a VLAN that is in no network of the DHCP server (any more) can still
    # be asked for, and the form shows it
    text = client(db).get('/?vlan=777&history=1').get_data(as_text=True)
    assert db.asked[-1] == (None, None, True, 500, 777)
    assert '<option value="777" selected>777</option>' in text
    # a database without the networks: a plain field instead of a list
    db.vlan_list = []
    text = client(db).get('/?vlan=10').get_data(as_text=True)
    assert '<select' not in text and '<input id="vlan" name="vlan" type="text"' in text and 'value="10"' in text


def test_nothing_found_offers_the_history():
    text = client(FakeDB()).get('/?q=192.0.2.99').get_data(as_text=True)
    assert 'Nobody holds a lease that matches right now' in text
    assert 'href="/?q=192.0.2.99&amp;history=1"' in text


def test_more_than_the_limit_says_so():
    text = client(FakeDB([lease()], truncated=True), LIMIT=1).get('/?q=192.0.2.0/24').get_data(as_text=True)
    assert 'Only the first 1 are shown' in text and '1+ lease' in text


def test_what_cannot_be_searched_for_is_explained_not_asked():
    db = FakeDB()
    page = client(db).get('/?q=banana/24')
    assert page.status_code == 400 and db.asked == []
    assert 'looks like a network' in page.get_data(as_text=True)


def test_what_was_typed_is_shown_as_text_not_as_markup():
    text = client(FakeDB()).get('/?q=<script>alert(1)</script>').get_data(as_text=True)
    assert '<script>' not in text and '&lt;script&gt;' in text


def test_networks_page():
    text = client(FakeDB()).get('/networks').get_data(as_text=True)
    assert '1 network' in text and 'OFFICE' in text and '25 %' in text
    assert 'href="/?q=192.0.2.0/24"' in text
    assert 'href="/?vlan=10"' in text


def test_the_api_answers_in_json_with_utc_times():
    db = FakeDB([lease()])
    data = client(db).get('/api/search?q=0000.5e00.5301&history=1').get_json()
    assert data['query'] == {'kind': 'mac', 'value': '00:00:5e:00:53:01'}
    assert data['history'] is True and data['truncated'] is False and data['vlan'] is None
    only_vlan = client(db).get('/api/search?vlan=10').get_json()
    assert only_vlan['query'] is None and only_vlan['vlan'] == 10 and len(only_vlan['leases']) == 1
    assert client(db).get('/api/search?vlan=99999').status_code == 400
    assert data['leases'][0]['first_seen'] == '2026-01-10T11:00:00Z'
    assert data['leases'][0]['port'] == 'ge-0/0/7.0:office'
    assert client(db).get('/api/search').status_code == 400
    assert client(db).get('/api/search?q=x').status_code == 400
    assert client(db).get('/api/networks').get_json()['networks'][0]['name'] == 'OFFICE'


def test_a_database_that_is_away_is_said_plainly():
    c = client(FakeDB(broken=True))
    page = c.get('/?q=192.0.2.57')
    assert page.status_code == 503
    text = page.get_data(as_text=True)
    assert 'could not be read right now' in text and 'connection refused' not in text
    assert c.get('/api/search?q=192.0.2.57').status_code == 503
    assert c.get('/healthz').status_code == 503


def test_health():
    assert client(FakeDB()).get('/healthz').get_data(as_text=True) == 'ok\n'
    old = client(FakeDB(version=1)).get('/healthz')
    assert old.status_code == 503 and 'schema version 1' in old.get_data(as_text=True)


def test_nothing_is_cached_and_nothing_foreign_is_loaded():
    page = client(FakeDB()).get('/')
    assert page.headers['Cache-Control'] == 'no-store'
    assert "default-src 'none'" in page.headers['Content-Security-Policy']
    assert 'Set-Cookie' not in page.headers
    text = page.get_data(as_text=True)
    assert '<script' not in text and 'http://' not in text and 'https://' not in text


def test_only_reading_is_possible():
    c = client(FakeDB())
    assert c.post('/', data={'q': 'x'}).status_code == 405
    assert c.get('/no-such-page').status_code == 404
