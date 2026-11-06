"""
Vercel Python Serverless Function entrypoint for Guinness Guide — Switzerland Venue & Menu Finder.
Routes /api/* requests (and static asset fallbacks) to StoutScoutHandler in app_server.py.
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app_server import StoutScoutHandler  # noqa: E402


class handler(StoutScoutHandler):
    """Vercel serverless HTTP handler."""

    pass
