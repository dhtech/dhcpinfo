# SPDX-License-Identifier: GPL-3.0-or-later
"""For a WSGI server:  gunicorn dhcpinfo.wsgi:app"""
from .app import create_app

app = create_app()
