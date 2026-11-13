# SPDX-License-Identifier: GPL-3.0-or-later
"""The web application: a search box over the DHCP lease history.

Nothing is written anywhere, nobody logs in, no cookie is set: every page
is a GET that reads the database. Who may see it is the business of
whatever stands in front (a reverse proxy, a firewall) - lease data says
who was where, and is not for everybody.
"""
from __future__ import annotations

import datetime
import os
import zoneinfo

from flask import Flask, jsonify, render_template, request

from . import __version__, query as q
from .db import SCHEMA_NEEDED, Database

DEFAULT_LIMIT = 500


def create_app(db=None, config: dict | None = None) -> Flask:
    """The application. DB is anything with Database's methods (the
    tests hand in their own); by default it is made from DHCPINFO_DSN."""
    app = Flask(__name__)
    app.config.update(
        DSN=os.environ.get('DHCPINFO_DSN', ''),
        LIMIT=int(os.environ.get('DHCPINFO_LIMIT', DEFAULT_LIMIT)),
        TIMEZONE=os.environ.get('DHCPINFO_TIMEZONE', 'UTC'),
        TITLE=os.environ.get('DHCPINFO_TITLE', 'DHCP leases'),
    )
    app.config.update(config or {})
    if db is None:
        if not app.config['DSN']:
            raise RuntimeError('DHCPINFO_DSN is not set: no database to read')
        db = Database(app.config['DSN'])
    tz = zoneinfo.ZoneInfo(app.config['TIMEZONE'])

    @app.template_filter('when')
    def when(value):
        """A time in the configured zone; nothing for no time."""
        if value is None:
            return ''
        return value.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')

    @app.context_processor
    def common():
        return {'title': app.config['TITLE'], 'version': __version__, 'timezone': app.config['TIMEZONE']}

    @app.after_request
    def headers(response):
        # everything on the pages is our own: no script, no style and no
        # picture from anywhere else, and nobody may frame them
        response.headers.setdefault('Content-Security-Policy',
                                    "default-src 'none'; style-src 'self'; img-src 'self'; "
                                    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        # lease data is not for a shared cache
        response.headers.setdefault('Cache-Control', 'no-store')
        return response

    class Search:
        """What this request asks for, and what was found."""
        query = None        # from the search box
        vlan = None         # the VLAN filter
        history = False
        problem = None
        rows: list = []
        truncated = False

        @property
        def asked(self):
            return self.query is not None or self.vlan is not None

    def run_search():
        s = Search()
        s.history = request.args.get('history') in ('1', 'on', 'true')
        try:
            s.query = q.parse(request.args.get('q'))
            s.vlan = q.parse_vlan(request.args.get('vlan'))
        except q.Unusable as exc:
            s.query, s.vlan, s.problem = None, None, str(exc)
            return s
        if s.asked:
            s.rows, s.truncated = db.search(s.query, s.history, app.config['LIMIT'], s.vlan)
        return s

    @app.get('/')
    def index():
        s = run_search()
        totals = db.totals() if not s.asked and s.problem is None else None
        return render_template('index.html', s=s, history=s.history, typed=request.args.get('q', ''),
                               typed_vlan=request.args.get('vlan', '').strip(), vlans=db.vlans(),
                               totals=totals, limit=app.config['LIMIT']), (400 if s.problem else 200)

    @app.get('/networks')
    def networks():
        return render_template('networks.html', networks=db.networks())

    @app.get('/api/search')
    def api_search():
        s = run_search()
        if s.problem:
            return jsonify(error=s.problem), 400
        if not s.asked:
            return jsonify(error='Give a query: ?q=<address, network, hardware address, host name or '
                                 '"vlan N"> and/or ?vlan=<number>'), 400
        return jsonify(query={'kind': s.query.kind, 'value': s.query.value} if s.query else None,
                       vlan=s.vlan, history=s.history, truncated=s.truncated,
                       leases=[_plain(row) for row in s.rows])

    @app.get('/api/networks')
    def api_networks():
        return jsonify(networks=[_plain(row) for row in db.networks()])

    @app.get('/healthz')
    def healthz():
        """For a monitor: 200 when the database answers and has the
        tables this program reads."""
        try:
            version = db.schema_version()
        except Exception as exc:    # whatever it is, the answer is "not healthy"
            app.logger.warning('health check: %s', exc)
            return 'database not reachable\n', 503, {'Content-Type': 'text/plain; charset=utf-8'}
        if version < SCHEMA_NEEDED:
            return ('lease2db schema version %d, need %d\n' % (version, SCHEMA_NEEDED), 503,
                    {'Content-Type': 'text/plain; charset=utf-8'})
        return 'ok\n', 200, {'Content-Type': 'text/plain; charset=utf-8'}

    @app.errorhandler(Exception)
    def failed(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return exc
        # the database is away, or something of ours broke: say so
        # plainly, and keep the details for the log
        app.logger.exception('request failed')
        message = 'The lease database could not be read right now.'
        if request.path.startswith('/api/'):
            return jsonify(error=message), 503
        return render_template('error.html', message=message), 503

    return app


def _plain(row: dict) -> dict:
    """A row for JSON: times as ISO 8601, numbers as numbers."""
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime.datetime):
            out[key] = value.astimezone(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        elif value is not None and type(value).__name__ == 'Decimal':
            out[key] = float(value)
        else:
            out[key] = value
    return out
