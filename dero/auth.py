"""Identity comes from Authelia via the reverse proxy (forward auth headers)."""
import hmac
from functools import wraps

from flask import abort, current_app, g, request
from itsdangerous import BadData, URLSafeTimedSerializer

from .db import get_db, now_iso


def _csrf_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="csrf")


def csrf_token() -> str:
    return _csrf_serializer().dumps(g.user["username"])


def load_user():
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
