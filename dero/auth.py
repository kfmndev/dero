"""Authentication for the admin UI.

AUTH_MODE=basic  HTTP Basic auth against a users file (`username:role:hash`, role = admin|user).
AUTH_MODE=none   no authentication: everyone is an admin named NONE_USER (trusted networks only!).
AUTH_MODE=proxy  identity headers set by a reverse proxy doing SSO (e.g. Authelia forward auth).
"""

import hmac
import os
from functools import wraps

from flask import Response, abort, current_app, g, request
from itsdangerous import BadData, URLSafeTimedSerializer

from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, now_iso

_DUMMY_HASH = generate_password_hash("dero")  # compared against for unknown users (timing)
_cache: dict = {}


def _csrf_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="csrf")


def csrf_token() -> str:
    return _csrf_serializer().dumps(g.user["username"])


def load_users(path: str) -> dict:
    """Parse the users file, re-reading it only when it changed on disk."""
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return {}
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    users = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":", 2)  # the hash itself contains ':' and '$'
            if len(parts) == 3 and parts[1] in ("admin", "user") and parts[0]:
                users[parts[0]] = (parts[1], parts[2])
    _cache[path] = (mtime, users)
    return users


def _unauthorized():
    abort(
        Response(
            "Authentication required.",
            401,
            {"WWW-Authenticate": 'Basic realm="dero", charset="UTF-8"', "Cache-Control": "no-store"},
        )
    )


def _identify_basic():
    creds = request.authorization
    if not creds or creds.type != "basic" or not creds.username:
        _unauthorized()
    entry = load_users(current_app.config["USERS_FILE"]).get(creds.username)
    ok = check_password_hash(entry[1] if entry else _DUMMY_HASH, creds.password or "")
    if not (entry and ok):
        _unauthorized()
    return creds.username, entry[0] == "admin"


def _identify_proxy():
    cfg = current_app.config
    secret = cfg["PROXY_SECRET"]
    if secret and not hmac.compare_digest(request.headers.get("X-Proxy-Secret", ""), secret):
        abort(403)

    username = request.headers.get(cfg["USER_HEADER"], "").strip()
    if not username:
        abort(403)
    groups = {x.strip() for x in request.headers.get(cfg["GROUPS_HEADER"], "").split(",") if x.strip()}
    is_admin = cfg["ADMIN_GROUP"] in groups
    if not (is_admin or cfg["USER_GROUP"] in groups):
        abort(403)
    return username, is_admin


def load_user():
    mode = current_app.config["AUTH_MODE"]
    if mode == "basic":
        username, is_admin = _identify_basic()
    elif mode == "none":
        username, is_admin = current_app.config["NONE_USER"], True
    else:
        username, is_admin = _identify_proxy()

    db = get_db()
    db.execute("INSERT OR IGNORE INTO users(username, first_seen_at) VALUES(?, ?)", (username, now_iso()))
    db.commit()
    g.user = {"username": username, "is_admin": is_admin}

    if request.method == "POST":
        try:
            who = _csrf_serializer().loads(request.form.get("csrf", ""), max_age=8 * 3600)
        except BadData:
            abort(400, "Invalid or expired form token.")
        if who != username:
            abort(400, "Invalid form token.")


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not g.user["is_admin"]:
            abort(403)
        return view(*a, **kw)

    return wrapper
