import os
import secrets
import sqlite3

from flask import Flask, abort, current_app, flash, g, make_response, redirect, render_template, request, url_for, Blueprint

from . import auth, db, resolve
from .version import build_info


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get("DATABASE", "dero.db"),
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        AUTH_MODE=os.environ.get("AUTH_MODE", "basic"),
        USERS_FILE=os.environ.get("USERS_FILE", "users.txt"),
        NONE_USER=os.environ.get("NONE_USER", "admin"),
        PROXY_SECRET=os.environ.get("PROXY_SECRET", ""),
        USER_HEADER=os.environ.get("USER_HEADER", "Remote-User"),
        GROUPS_HEADER=os.environ.get("GROUPS_HEADER", "Remote-Groups"),
        USER_GROUP=os.environ.get("USER_GROUP", "dero-users"),
        ADMIN_GROUP=os.environ.get("ADMIN_GROUP", "dero-admins"),
        ADMIN_PATH=os.environ.get("ADMIN_PATH", "/admin"),
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(db.close_db)
    if app.config["AUTH_MODE"] not in ("basic", "proxy", "none"):
        raise RuntimeError("AUTH_MODE must be 'basic', 'proxy' or 'none'")
    if app.config["AUTH_MODE"] == "none":
        app.logger.warning("AUTH_MODE=none: the admin UI at %s has NO authentication. "
                           "Anyone who can reach it is an admin.", app.config["ADMIN_PATH"])
    if app.config["AUTH_MODE"] == "basic" and not auth.load_users(app.config["USERS_FILE"]):
        app.logger.warning("No users found in %s: nobody can sign in. "
                           "Create one with: python -m dero.passwd --file %s <name> --role admin",
                           app.config["USERS_FILE"], app.config["USERS_FILE"])
    db_dir = os.path.dirname(os.path.abspath(app.config["DATABASE"]))
    os.makedirs(db_dir, exist_ok=True)
    with app.app_context():
        db.init_db()
        env_fallback = os.environ.get("FALLBACK_URL", "")
        if env_fallback and not db.get_setting("fallback_url"):
            db.set_setting("fallback_url", resolve.validate_url(env_fallback))

    admin_path = "/" + app.config["ADMIN_PATH"].strip("/")
    app.config["ADMIN_PATH"] = admin_path
    app.register_blueprint(admin, url_prefix=admin_path)
    app.jinja_env.globals["csrf_token"] = auth.csrf_token
    app.context_processor(lambda: {"build": build_info()})

    @app.after_request
    def headers(resp):
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def follow(path):
        url, _counted = resolve.resolve(path)
        if not url:
            abort(404)
        resp = redirect(url, 302)  # 302: never cached, so counting/disabling keep working
        resp.headers["Cache-Control"] = "no-store"
        return resp

    return app


# ---------------------------------------------------------------- admin UI
admin = Blueprint("admin", __name__)
admin.before_request(auth.load_user)

SLUG_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _random_slug(n=5):
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(n))


def _own_or_admin(link_id):
    row = db.get_db().execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if not row or not (g.user["is_admin"] or row["created_by"] == g.user["username"]):
        abort(404)
    return row


# column -> SQL used for ORDER BY (the keys are the only values ever put into the query)
SORTS = {
    "created": "created_at",
    "slug": "slug COLLATE NOCASE",
    "target": "target COLLATE NOCASE",
    "creator": "created_by COLLATE NOCASE",
    "expires": "expires_at IS NULL, expires_at",
    "visits": "visits",
}
STATUSES = ("active", "disabled", "expired")
# (sort key, direction) -> label for the "Sort by" dropdown
ORDER_LABELS = {
    ("created", "desc"): "Newest first", ("created", "asc"): "Oldest first",
    ("visits", "desc"): "Most visits", ("visits", "asc"): "Fewest visits",
    ("slug", "asc"): "Short link A–Z", ("slug", "desc"): "Short link Z–A",
    ("target", "asc"): "Target A–Z", ("target", "desc"): "Target Z–A",
    ("expires", "asc"): "Expiring soonest", ("expires", "desc"): "Expiring latest",
    ("creator", "asc"): "Creator A–Z", ("creator", "desc"): "Creator Z–A",
}


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@admin.get("/")
def index():
    conn = db.get_db()
    q = request.args.get("q", "").strip()[:200]
    status = request.args.get("status", "")
    status = status if status in STATUSES else ""
    owner = request.args.get("owner", "").strip() if g.user["is_admin"] else ""
    sort = request.args.get("sort", "created")
    sort = sort if sort in SORTS else "created"
    direction = "asc" if request.args.get("dir") == "asc" else "desc"
    key, _, d = request.args.get("order", "").partition(":")  # the dropdown sends "key:dir"
    if key in SORTS and d in ("asc", "desc"):
        sort, direction = key, d

    where, args = [], []
    if not g.user["is_admin"]:
        where.append("created_by = ?")
        args.append(g.user["username"])
    elif owner:
        where.append("created_by = ?")
        args.append(owner)
    if q:
        where.append("(slug LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\' OR created_by LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 3
    now = db.now_iso()
    if status == "active":
        where.append("enabled = 1 AND (expires_at IS NULL OR expires_at > ?)")
        args.append(now)
    elif status == "disabled":
        where.append("enabled = 0")
    elif status == "expired":
        where.append("expires_at IS NOT NULL AND expires_at <= ?")
        args.append(now)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    order = f"{SORTS[sort]} {direction.upper()}, id DESC"
    links = conn.execute(f"SELECT * FROM links{clause} ORDER BY {order}", args).fetchall()

    scope = "" if g.user["is_admin"] else " WHERE created_by = ?"
    overall = conn.execute(f"SELECT COUNT(*) FROM links{scope}",
                           () if g.user["is_admin"] else (g.user["username"],)).fetchone()[0]
    owners = ([r[0] for r in conn.execute("SELECT DISTINCT created_by FROM links ORDER BY created_by COLLATE NOCASE")]
              if g.user["is_admin"] else [])

    def sort_url(key):
        nxt = "asc" if (sort == key and direction == "desc") else "desc" if sort == key else (
            "asc" if key in ("slug", "target", "creator", "expires") else "desc")
        params = {"q": q, "status": status, "owner": owner, "sort": key, "dir": nxt}
        return url_for("admin.index", **{k: v for k, v in params.items() if v})

    return render_template(
        "index.html", links=links, total=sum(l["visits"] for l in links), overall=overall,
        base=request.host_url, q=q, status=status, owner=owner, owners=owners,
        sort=sort, direction=direction, sort_url=sort_url, now=now,
        order_options=[(f"{k}:{d}", label) for (k, d), label in ORDER_LABELS.items()
                       if g.user["is_admin"] or k != "creator"],
        filtered=bool(q or status or owner), back=request.full_path.rstrip("?"))


def _back():
    """Return to the page (filters, sorting) a form was submitted from; same-site paths only."""
    back = request.form.get("back", "")
    if back.startswith(current_app.config["ADMIN_PATH"]) and not back.startswith("//") and "\\" not in back:
        return redirect(back)
    return redirect(url_for("admin.index"))


@admin.post("/links")
def create_link():
    conn = db.get_db()
    try:
        target = resolve.validate_url(request.form.get("target", ""))
        slug = request.form.get("slug", "").strip()
        expires = request.form.get("expires_at", "").strip() or None
        if expires:
            from datetime import datetime
            try:
                expires = datetime.strptime(expires, "%Y-%m-%d").strftime("%Y-%m-%dT23:59:59Z")
            except ValueError:
                raise resolve.ValidationError("Expiry must be a date (YYYY-MM-DD).")
        for _ in range(10):
            candidate = resolve.validate_slug(slug) if slug else _random_slug()
            if candidate in (current_app.config["ADMIN_PATH"].strip("/").split("/")[0], "static"):
                raise resolve.ValidationError(f"'{candidate}' is reserved.")
            try:
                conn.execute(
                    "INSERT INTO links(slug, target, created_by, created_at, expires_at) VALUES(?,?,?,?,?)",
                    (candidate, target, g.user["username"], db.now_iso(), expires))
                conn.commit()
                flash(f"Created {request.host_url}{candidate}")
                break
            except sqlite3.IntegrityError:
                if slug:
                    raise resolve.ValidationError(f"Slug '{slug}' is already taken.")
        else:
            raise resolve.ValidationError("Could not find a free slug, try again.")
    except resolve.ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.index"))


@admin.post("/links/<int:link_id>/toggle")
def toggle_link(link_id):
    _own_or_admin(link_id)
    conn = db.get_db()
    conn.execute("UPDATE links SET enabled = 1 - enabled WHERE id = ?", (link_id,))
    conn.commit()
    return _back()


@admin.post("/links/<int:link_id>/delete")
def delete_link(link_id):
    _own_or_admin(link_id)
    conn = db.get_db()
    conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    conn.commit()
    return _back()


# ---- admin only: rules + fallback
@admin.get("/rules")
@auth.admin_required
def rules():
    rows = db.get_db().execute("SELECT * FROM rules ORDER BY priority, id").fetchall()
    return render_template("rules.html", rules=rows, fallback=db.get_setting("fallback_url"))


@admin.post("/rules")
@auth.admin_required
def create_rule():
    f = request.form
    try:
        pattern = f.get("pattern", "").strip().strip("/")
        mtype = f.get("match_type", "glob")
        target = f.get("target", "").strip()
        resolve.validate_rule(pattern, mtype, target)
        try:
            priority = int(f.get("priority") or 100)
        except ValueError:
            raise resolve.ValidationError("Priority must be a number.")
        conn = db.get_db()
        conn.execute("INSERT INTO rules(pattern, match_type, target, priority, created_by, created_at) "
                     "VALUES(?,?,?,?,?,?)",
                     (pattern, mtype, target, priority, g.user["username"], db.now_iso()))
        conn.commit()
    except resolve.ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.rules"))


@admin.post("/rules/<int:rule_id>/priority")
@auth.admin_required
def rule_priority(rule_id):
    try:
        prio = int(request.form.get("priority", ""))
    except ValueError:
        flash("Priority must be a number.", "error")
        return redirect(url_for("admin.rules"))
    conn = db.get_db()
    conn.execute("UPDATE rules SET priority = ? WHERE id = ?", (prio, rule_id))
    conn.commit()
    return redirect(url_for("admin.rules"))


@admin.post("/rules/<int:rule_id>/toggle")
@auth.admin_required
def rule_toggle(rule_id):
    conn = db.get_db()
    conn.execute("UPDATE rules SET enabled = 1 - enabled WHERE id = ?", (rule_id,))
    conn.commit()
    return redirect(url_for("admin.rules"))


@admin.post("/rules/<int:rule_id>/delete")
@auth.admin_required
def rule_delete(rule_id):
    conn = db.get_db()
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    return redirect(url_for("admin.rules"))


@admin.post("/settings/fallback")
@auth.admin_required
def set_fallback():
    value = request.form.get("fallback_url", "").strip()
    try:
        db.set_setting("fallback_url", resolve.validate_url(value) if value else "")
        flash("Fallback saved." if value else "Fallback cleared (unknown links return 404).")
    except resolve.ValidationError as exc:
        flash(str(exc), "error")
    return redirect(url_for("admin.rules"))
