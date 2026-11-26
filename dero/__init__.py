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


def _config_from_environment():
    env = os.environ.get

    return dict(
        DATABASE=env("DATABASE", "dero.db"),
        SECRET_KEY=env("SECRET_KEY") or secrets.token_hex(32),
        AUTH_MODE=env("AUTH_MODE", "basic"),
        USERS_FILE=env("USERS_FILE", "users.txt"),
        NONE_USER=env("NONE_USER", "admin"),
        PROXY_SECRET=env("PROXY_SECRET", ""),
        USER_HEADER=env("USER_HEADER", "Remote-User"),
        GROUPS_HEADER=env("GROUPS_HEADER", "Remote-Groups"),
        USER_GROUP=env("USER_GROUP", "dero-users"),
        ADMIN_GROUP=env("ADMIN_GROUP", "dero-admins"),
        ADMIN_PATH=env("ADMIN_PATH", "/admin"),
        BASE_URL=env("BASE_URL", ""),
    )


def _check_auth_mode(app):
    """Refuse an unknown mode, and warn where the setup leaves the admin UI open or locked."""
    mode = app.config["AUTH_MODE"]

    if mode not in ("basic", "proxy", "none"):
        raise RuntimeError("AUTH_MODE must be 'basic', 'proxy' or 'none'")

    if mode == "none":
        app.logger.warning(
            "AUTH_MODE=none: the admin UI at %s has NO authentication. Anyone who can reach it is an admin.",
            app.config["ADMIN_PATH"],
        )

    if mode == "basic" and not auth.load_users(app.config["USERS_FILE"]):
        app.logger.warning(
            "No users found in %s: nobody can sign in. "
            "Create one with: python -m dero.passwd --file %s <name> --role admin",
            app.config["USERS_FILE"],
            app.config["USERS_FILE"],
        )


def _prepare_database(app):
    """Create the directory and the tables, and take the fallback address from FALLBACK_URL if none is saved yet."""
    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)

    with app.app_context():
        db.init_db()
        env_fallback = os.environ.get("FALLBACK_URL", "")

        if env_fallback and not db.get_setting("fallback_url"):
            db.set_setting("fallback_url", resolve.validate_url(env_fallback))


def _add_short_link_routes(app):
    """Security headers on every answer, and the public route that follows a short link."""

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


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(_config_from_environment())

    if test_config:
        app.config.update(test_config)
    app.teardown_appcontext(db.close_db)
    _check_auth_mode(app)
    _prepare_database(app)

    app.config["BASE_URL"] = normalise_base_url(app.config["BASE_URL"])
    admin_path = "/" + app.config["ADMIN_PATH"].strip("/")
    app.config["ADMIN_PATH"] = admin_path
    app.register_blueprint(admin_blueprint, url_prefix=admin_path)
    app.jinja_env.globals["csrf_token"] = auth.csrf_token
    app.context_processor(lambda: {"build": build_info(), "highlight_on": request.cookies.get("dero_hl") != "0"})
    display.register(app)
    _add_short_link_routes(app)

    return app
