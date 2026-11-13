# dhcpinfo

`dhcpinfo` is a small web page for one question: **who has, or had, this
address?** It searches the DHCP lease history that
[lease2db](https://github.com/dhtech/lease2db) keeps in PostgreSQL from an
ISC dhcpd lease file.

Type an address, a network, a hardware address, a VLAN or part of a host
name into one box:

| You type | You get |
|---|---|
| `192.0.2.57` | who has the address now - and, with history, who had it before |
| `192.0.2.0/24` | everybody in the network |
| `00:00:5e:00:53:01`, `0000.5e00.5301`, `00-00-5E-00-53-01` | the addresses this client holds or held |
| `00:00:5e` | every client whose hardware address starts like that (a vendor) |
| `laptop` | every host name that contains it |
| `vlan 10` | everybody in that VLAN |

Two controls next to the box shape every search:

- **Search in** *Current leases* (the default: who has it right now) or
  *History* (current leases and those that are over).
- **Only VLAN** narrows whatever you search for to one VLAN - a host name
  or a vendor prefix within VLAN 10, say. With the box left empty it
  lists the whole VLAN.

Every result shows the address, the hardware address, the host name the
client sent, the network and VLAN, the switch and port it sits behind
(the relay's option 82, when there is one), and when the lease began, was
renewed and ends. Each value is a link to the next search. A second page
lists the networks with how full they are.

It only reads. There is no login, no cookie, no JavaScript and nothing
loaded from anywhere else; graphs belong in Grafana, which can read the
same database and lease2db's metrics.

## Requirements

- A database filled by lease2db **0.2.0 or later** (schema version 2).
- Python 3.11 or later with Flask 3, psycopg 3 and psycopg-pool. On
  Debian 13: `apt install python3-flask python3-psycopg python3-psycopg-pool gunicorn`.

## The database role

Give dhcpinfo a role of its own that can only read (`lease2db` here is the
role that owns the tables):

```sql
CREATE ROLE dhcp_read LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE dhcp TO dhcp_read;
GRANT USAGE ON SCHEMA public TO dhcp_read;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dhcp_read;
ALTER DEFAULT PRIVILEGES FOR ROLE lease2db IN SCHEMA public GRANT SELECT ON TABLES TO dhcp_read;
```

On top of that dhcpinfo asks the server to refuse writes on every
connection it opens, so it cannot change the history even with a role
that could.

## Run

Download the release archive (or `pip install` the wheel), then:

```sh
export DHCPINFO_DSN='host=db.example.net dbname=dhcp user=dhcp_read password=... sslmode=verify-full'
gunicorn --bind 127.0.0.1:8000 dhcpinfo.wsgi:app
```

| Variable | Default | |
|---|---|---|
| `DHCPINFO_DSN` | *(required)* | PostgreSQL connection string or URL. `sslcert`/`sslkey`/`sslrootcert` work, so it can log in with a client certificate instead of a password |
| `DHCPINFO_TIMEZONE` | `UTC` | the time zone the pages show times in, e.g. `Europe/Stockholm` |
| `DHCPINFO_LIMIT` | `500` | the most leases one search shows |
| `DHCPINFO_TITLE` | `DHCP leases` | the name at the top of the pages |

An example systemd unit and an nginx server block are in
[`contrib/`](contrib/).

### Who may see it

**Put it behind something that asks who is there.** Lease data says which
device was where and when; dhcpinfo itself lets everybody who can reach it
search everything. Bind gunicorn to the loopback address and let a reverse
proxy with authentication (or a firewall that only admits your operators)
stand in front.

## For other programs

The same searches answer in JSON:

```
GET /api/search?q=192.0.2.57            who has it now
GET /api/search?q=192.0.2.57&history=1  and who had it
GET /api/search?q=laptop&vlan=10         narrowed to a VLAN
GET /api/search?vlan=10                  everybody in a VLAN
GET /api/networks                        the networks and their usage
GET /healthz                             200 "ok" when the database answers
```

```json
{
  "query": {"kind": "ip", "value": "192.0.2.57"},
  "vlan": null,
  "history": false,
  "truncated": false,
  "leases": [{
    "ip": "192.0.2.57", "mac": "00:00:5e:00:53:01", "hostname": "laptop",
    "scope": "OFFICE", "vlan": 10, "network": "192.0.2.0/24",
    "first_seen": "2026-01-10T11:00:00Z", "starts": "2026-01-10T11:30:00Z",
    "ends": "2026-01-10T12:30:00Z", "state": "active", "active": true,
    "switch": "sw-a1", "port": "ge-0/0/7.0:office", "vendor_class": null
  }]
}
```

`kind` is one of `ip`, `net`, `mac`, `mac_prefix`, `name`, `vlan`; `query`
is null when only `vlan=` was given. Times in JSON
are UTC. `switch` and `port` are the relay's remote id and circuit id: as
text when the relay sent text, otherwise as hex (`00:04:00:64:01:0c`) -
decoding a vendor's packed format is up to the caller.

A page address is a search too, so other tools can link straight to one:
`https://dhcpinfo.example.net/?q=192.0.2.57&history=1`.

## Good to know

- "Now" means: dhcpd's latest word about the address is an active lease
  that has not run out. A lease that ran out without dhcpd noting it shows
  as *ended*.
- A lease has a VLAN when its address lies in one of the DHCP server's
  networks and lease2db knows that network's VLAN number (see lease2db's
  `-scopes`).
- A client with a fixed address (`fixed-address` in dhcpd's configuration)
  never appears: dhcpd does not write those to its lease file.
- The history is as long as you let lease2db keep it.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]' 'psycopg[binary]'
pytest
```

The tests of the database queries need a real PostgreSQL and are skipped
without one; point `DHCPINFO_TEST_DSN` at a database the tests may empty
and fill. `tests/schema.sql` is a copy of lease2db's schema for that.

A release is a tag: set `__version__` in `dhcpinfo/__init__.py`, push
`vX.Y.Z`, and the archive and wheel are published.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
