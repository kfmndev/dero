"""dero: a small, privacy-first URL shortener. `create_app()` builds the Flask app; the pieces are

    resolve.py   slugs, URLs and rules: what a request resolves to
    query.py     the search language of the links table
    forms.py     reading the New link / edit forms
    display.py   how slugs and short links are drawn in pages
    urls.py      the public base address
    auth.py      who the user is (basic, proxy or none) and CSRF
    db.py        the SQLite connection and settings
    admin/       the admin UI (links, live visits, rules)
"""
import os
import secrets

from flask import Flask, abort, redirect, request

from . import auth, db, display, resolve
from .admin import bp as admin_blueprint
from .urls import normalise_base_url
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
        BASE_URL=os.environ.get("BASE_URL", ""),
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

    app.config["BASE_URL"] = normalise_base_url(app.config["BASE_URL"])
    admin_path = "/" + app.config["ADMIN_PATH"].strip("/")
    app.config["ADMIN_PATH"] = admin_path
    app.register_blueprint(admin_blueprint, url_prefix=admin_path)
    app.jinja_env.globals["csrf_token"] = auth.csrf_token
    app.context_processor(lambda: {"build": build_info(), "highlight_on": request.cookies.get("dero_hl") != "0"})
    display.register(app)

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
