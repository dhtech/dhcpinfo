-- The tables, function and views of lease2db, schema version 2
-- (https://github.com/dhtech/lease2db, internal/store/store.go: its two
-- migrations, in order). ONLY for this repository's tests: in real use
-- lease2db creates them. Update this file when lease2db's schema changes.

CREATE TABLE lease2db_schema (version integer NOT NULL);
INSERT INTO lease2db_schema VALUES (2);

-- migration 1
CREATE TABLE leases (
	id           bigserial PRIMARY KEY,
	ip           inet NOT NULL,
	mac          macaddr,
	first_seen   timestamptz NOT NULL,
	starts       timestamptz NOT NULL,
	ends         timestamptz,
	state        text NOT NULL,
	current      boolean NOT NULL DEFAULT true,
	hostname     text,
	circuit_id   text,
	remote_id    text,
	vendor_class text,
	updated      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE leases IS 'One row for every time a client held an address (lease2db).';
COMMENT ON COLUMN leases.first_seen IS 'when this client got the address';
COMMENT ON COLUMN leases.starts IS 'its latest renewal';
COMMENT ON COLUMN leases.ends IS 'when the lease runs out, or ended; NULL = never';
COMMENT ON COLUMN leases.state IS 'dhcpd''s binding state: active, free, expired, released, abandoned, ...';
COMMENT ON COLUMN leases.current IS 'the latest row of its address';
COMMENT ON COLUMN leases.circuit_id IS 'relay agent option 82: where the client is plugged in';
CREATE UNIQUE INDEX leases_current ON leases (ip) WHERE current;
CREATE INDEX leases_ip_time ON leases (ip, first_seen);
CREATE INDEX leases_mac ON leases (mac);
CREATE INDEX leases_ends ON leases (ends);

CREATE TABLE scopes (
	network   cidr PRIMARY KEY,
	name      text NOT NULL,
	vlan      integer,
	gateway   inet,
	addresses integer NOT NULL,
	active    boolean NOT NULL,
	updated   timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE scopes IS 'The networks the DHCP server hands addresses out in (lease2db).';
COMMENT ON COLUMN scopes.addresses IS 'addresses in its dynamic ranges';
COMMENT ON COLUMN scopes.active IS 'in the server''s configuration now';

CREATE VIEW leases_active AS
	SELECT l.*, s.network, s.name AS scope, s.vlan
	FROM leases l
	LEFT JOIN scopes s ON s.active AND l.ip << s.network
	WHERE l.current AND l.state = 'active' AND (l.ends IS NULL OR l.ends > now());
COMMENT ON VIEW leases_active IS 'Who holds which address right now.';

CREATE VIEW scopes_usage AS
	SELECT s.network, s.name, s.vlan, s.addresses, count(l.id) AS leases
	FROM scopes s
	LEFT JOIN leases l ON l.current AND l.state = 'active'
		AND (l.ends IS NULL OR l.ends > now()) AND l.ip << s.network
	WHERE s.active
	GROUP BY s.network, s.name, s.vlan, s.addresses;
COMMENT ON VIEW scopes_usage IS 'How full every network is right now.';

-- migration 2
DROP VIEW scopes_usage;
DROP VIEW leases_active;
ALTER TABLE leases
	ALTER COLUMN circuit_id TYPE bytea USING convert_to(circuit_id, 'UTF8'),
	ALTER COLUMN remote_id TYPE bytea USING convert_to(remote_id, 'UTF8');
COMMENT ON COLUMN leases.circuit_id IS 'relay agent option 82, circuit id: the bytes the relay sent';
COMMENT ON COLUMN leases.remote_id IS 'relay agent option 82, remote id: the bytes the relay sent';

CREATE FUNCTION lease2db_show(bytea) RETURNS text
	LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
	SELECT CASE
		WHEN $1 IS NULL THEN NULL
		WHEN encode($1, 'hex') ~ '^(2[0-9a-f]|[346][0-9a-f]|5[0-9abd-f]|7[0-9a-e])*$'
			THEN convert_from($1, 'UTF8')
		ELSE regexp_replace(encode($1, 'hex'), '(..)(?!$)', '\1:', 'g')
	END
$fn$;
COMMENT ON FUNCTION lease2db_show(bytea) IS
	'Bytes for reading: as text when all of them are printable ASCII, else as hex (00:04:00:64).';

CREATE VIEW leases_history AS
	SELECT l.id, l.ip, l.mac, l.first_seen, l.starts, l.ends, l.state, l.current,
	       (l.current AND l.state = 'active' AND (l.ends IS NULL OR l.ends > now())) AS active,
	       l.hostname, l.vendor_class, l.circuit_id, l.remote_id,
	       lease2db_show(l.circuit_id) AS circuit_id_text,
	       lease2db_show(l.remote_id) AS remote_id_text,
	       s.network, s.name AS scope, s.vlan, l.updated
	FROM leases l
	LEFT JOIN scopes s ON s.active AND l.ip << s.network;
COMMENT ON VIEW leases_history IS
	'Every holding of an address, with its network and the relay information made readable.';

CREATE VIEW leases_active AS SELECT * FROM leases_history WHERE active;
COMMENT ON VIEW leases_active IS 'Who holds which address right now.';

CREATE VIEW scopes_usage AS
	SELECT s.network, s.name, s.vlan, s.gateway, s.addresses, count(l.id) AS leases,
	       round(100.0 * count(l.id) / nullif(s.addresses, 0), 2) AS percent_used
	FROM scopes s
	LEFT JOIN leases l ON l.current AND l.state = 'active'
		AND (l.ends IS NULL OR l.ends > now()) AND l.ip << s.network
	WHERE s.active
	GROUP BY s.network, s.name, s.vlan, s.gateway, s.addresses;
COMMENT ON VIEW scopes_usage IS 'How full every network is right now.';

CREATE VIEW leases_totals AS
	SELECT count(*) FILTER (WHERE active) AS active_leases,
	       count(DISTINCT mac) FILTER (WHERE active) AS active_clients,
	       count(DISTINCT mac) AS clients_ever
	FROM leases_history;
COMMENT ON VIEW leases_totals IS 'Leases and clients right now, and clients ever seen.';
