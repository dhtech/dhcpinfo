# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from dhcpinfo import query


@pytest.mark.parametrize('text,kind,value', [
    ('192.0.2.57', 'ip', '192.0.2.57'),
    ('  192.0.2.57 ', 'ip', '192.0.2.57'),
    ('2001:db8::1', 'ip', '2001:db8::1'),
    ('192.0.2.0/24', 'net', '192.0.2.0/24'),
    ('192.0.2.57/24', 'net', '192.0.2.0/24'),          # a host with its mask
    ('00:00:5E:00:53:01', 'mac', '00:00:5e:00:53:01'),
    ('00-00-5e-00-53-01', 'mac', '00:00:5e:00:53:01'),
    ('0000.5e00.5301', 'mac', '00:00:5e:00:53:01'),
    ('00005e005301', 'mac', '00:00:5e:00:53:01'),
    ('00:00:5e', 'mac_prefix', '00:00:5e'),            # a vendor
    ('00-00-5E-00', 'mac_prefix', '00:00:5e:00'),
    ('00:00:5e:', 'mac_prefix', '00:00:5e'),
    ('laptop', 'name', 'laptop'),
    ('Anna-PC', 'name', 'Anna-PC'),
    ('cafe01', 'name', 'cafe01'),                      # hex digits, but a name
    ('dead.beef', 'name', 'dead.beef'),
    ('ab:cd', 'name', 'ab:cd'),                        # too short for a vendor
    ('vlan 10', 'vlan', '10'),
    ('VLAN950', 'vlan', '950'),
    ('vlan:10', 'vlan', '10'),
    ('vlan=4094', 'vlan', '4094'),
    ('vlan', 'name', 'vlan'),                          # the word alone is a name
    ('vlan-printer', 'name', 'vlan-printer'),
])
def test_what_was_typed(text, kind, value):
    q = query.parse(text)
    assert (q.kind, q.value) == (kind, value)
    assert q.text == text.strip()
    assert q.label


@pytest.mark.parametrize('text', ['', '   ', None])
def test_nothing_typed_is_no_query(text):
    assert query.parse(text) is None


@pytest.mark.parametrize('text,message', [
    ('192.0.2.0/99', 'looks like a network'),
    ('banana/24', 'looks like a network'),
    ('x', 'at least two characters'),
    ('a' * 101, 'too long'),
    ('vlan 0', '1 to 4094'),
    ('vlan 4095', '1 to 4094'),
])
def test_what_cannot_be_searched_for(text, message):
    with pytest.raises(query.Unusable, match=message):
        query.parse(text)


def test_wildcards_in_a_name_are_searched_for_not_obeyed():
    assert query.like_pattern('laptop') == '%laptop%'
    assert query.like_pattern('100%_done\\') == '%100\\%\\_done\\\\%'


def test_the_vlan_filter():
    assert query.parse_vlan('10') == 10
    assert query.parse_vlan(' 950 ') == 950
    assert query.parse_vlan('') is None and query.parse_vlan(None) is None
    for bad in ('0', '4095', 'ten', '-1', '1;2'):
        with pytest.raises(query.Unusable, match='1 to 4094'):
            query.parse_vlan(bad)
