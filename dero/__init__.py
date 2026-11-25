import os
import secrets
import sqlite3

from flask import Flask, abort, flash, g, make_response, redirect, render_template, request, url_for, Blueprint

from . import auth, db, resolve


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get("DATABASE", "dero.db"),
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        PROXY_SECRET=os.environ.get("PROXY_SECRET", ""),
        USER_HEADER=os.environ.get("USER_HEADER", "Remote-User"),
        GROUPS_HEADER=os.environ.get("GROUPS_HEADER", "Remote-Groups"),
        USER_GROUP=os.environ.get("USER_GROUP", "dero-users"),
        ADMIN_GROUP=os.environ.get("ADMIN_GROUP", "dero-admins"),
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(db.close_db)
    with app.app_context():
        db.init_db()
        env_fallback = os.environ.get("FALLBACK_URL", "")
        if env_fallback and not db.get_setting("fallback_url"):
            db.set_setting("fallback_url", resolve.validate_url(env_fallback))

    app.register_blueprint(admin)
    app.jinja_env.globals["csrf_token"] = auth.csrf_token

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
admin = Blueprint("admin", __name__, url_prefix="/_")
admin.before_request(auth.load_user)

SLUG_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _random_slug(n=5):
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(n))


def _own_or_admin(link_id):
    row = db.get_db().execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if not row or not (g.user["is_admin"] or row["created_by"] == g.user["username"]):
        abort(404)
    return row


@admin.get("/")
def index():
    q = "SELECT * FROM links"
    args = ()
    if not g.user["is_admin"]:
        q += " WHERE created_by = ?"
        args = (g.user["username"],)
    links = db.get_db().execute(q + " ORDER BY created_at DESC, id DESC", args).fetchall()
    total = sum(l["visits"] for l in links)
    return render_template("index.html", links=links, total=total, base=request.host_url)


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
    return redirect(url_for("admin.index"))


@admin.post("/links/<int:link_id>/delete")
def delete_link(link_id):
    _own_or_admin(link_id)
    conn = db.get_db()
    conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    conn.commit()
    return redirect(url_for("admin.index"))


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
