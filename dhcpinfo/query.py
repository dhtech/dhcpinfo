# SPDX-License-Identifier: GPL-3.0-or-later
"""What somebody typed into the search box, understood.

One box takes everything: an address, a network, a hardware address (in
any of the usual spellings, or the beginning of one), a VLAN ("vlan 10"),
or part of a host name. Any search can also be narrowed to one VLAN. This module only decides which it is - it knows nothing about the
web or the database, so it can be tested on its own.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

IP = 'ip'                 # one address
NET = 'net'               # every address in a network
MAC = 'mac'               # one hardware address
MAC_PREFIX = 'mac_prefix'  # hardware addresses that start like this
NAME = 'name'             # host names that contain this
VLAN = 'vlan'             # everybody in a VLAN

KINDS = {
    IP: 'address',
    NET: 'network',
    MAC: 'hardware address',
    MAC_PREFIX: 'hardware addresses starting with',
    NAME: 'host names containing',
    VLAN: 'VLAN',
}

_HEX12 = re.compile(r'^[0-9a-f]{12}$')
# the beginning of a hardware address, written with separators: aa:bb:cc
_PARTIAL = re.compile(r'^[0-9a-f]{2}([:-][0-9a-f]{2}){2,4}[:-]?$')
# "vlan 10", "vlan10", "vlan:10", "VLAN=10"
_VLAN = re.compile(r'^vlan\s*[:=]?\s*(\d+)$')
MAX_LENGTH = 100


class Unusable(ValueError):
    """The text cannot be searched for; the message says why."""


@dataclass(frozen=True)
class Query:
    kind: str
    value: str     # normalised: what the database is asked for
    text: str      # what was typed

    @property
    def label(self) -> str:
        return KINDS[self.kind]


def parse(text: str | None) -> Query | None:
    """The query in TEXT; None when there is nothing to search for."""
    text = (text or '').strip()
    if not text:
        return None
    if len(text) > MAX_LENGTH:
        raise Unusable('That is too long to search for.')
    low = text.lower()

    vlan = _VLAN.match(low)
    if vlan:
        return Query(VLAN, str(parse_vlan(vlan.group(1))), text)
    if '/' in low:
        try:
            net = ipaddress.ip_network(low, strict=False)
        except ValueError:
            raise Unusable('"%s" looks like a network but is not one.' % text)
        return Query(NET, str(net), text)
    try:
        return Query(IP, str(ipaddress.ip_address(low)), text)
    except ValueError:
        pass

    # aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff, aabb.ccdd.eeff, aabbccddeeff
    bare = re.sub(r'[:.\-]', '', low)
    if _HEX12.match(bare) and _mac_shaped(low):
        return Query(MAC, ':'.join(bare[i:i + 2] for i in range(0, 12, 2)), text)
    if _PARTIAL.match(low):
        pairs = re.findall(r'[0-9a-f]{2}', low)
        return Query(MAC_PREFIX, ':'.join(pairs), text)

    if len(text) < 2:
        raise Unusable('Give at least two characters of a host name.')
    return Query(NAME, text, text)


def parse_vlan(text: str | None) -> int | None:
    """The VLAN number in TEXT (the filter next to the search box);
    None when there is none."""
    text = (text or '').strip()
    if not text:
        return None
    if not text.isdigit() or not 1 <= int(text) <= 4094:
        raise Unusable('A VLAN is a number from 1 to 4094.')
    return int(text)


def _mac_shaped(low: str) -> bool:
    """Twelve hex digits in one of the spellings people use - not just
    any text that happens to consist of hex digits and dots."""
    return bool(re.match(r'^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$', low)
                or re.match(r'^([0-9a-f]{4}\.){2}[0-9a-f]{4}$', low)
                or _HEX12.match(low))


def like_pattern(text: str) -> str:
    """TEXT as the middle of a LIKE pattern: its own % _ and \\ are
    escaped, so they are searched for and not understood as wildcards."""
    return '%' + re.sub(r'([\\%_])', r'\\\1', text) + '%'
