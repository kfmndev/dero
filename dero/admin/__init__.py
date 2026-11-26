"""The admin UI (a Flask blueprint; the routes are in links.py, live.py and rules.py)."""

from flask import Blueprint

from .. import auth

bp = Blueprint("admin", __name__)
bp.before_request(auth.load_user)

# the route modules register themselves on bp when imported
from . import links, live, rules  # noqa: E402,F401
