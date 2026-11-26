"""The links: list, create, switch on and off, look up an address, edit, delete."""
import json
import sqlite3
from urllib.parse import urlsplit

from flask import flash, g, jsonify, redirect, request, url_for

from .. import db, resolve
from ..forms import parse_expiry, random_slug, reserved_slugs, slug_plan, validated
from ..urls import base_url
from . import bp
from .helpers import back, own_or_admin
from .listing import render_index

@bp.get("/")
def index():
    return render_index()

@bp.post("/links")
def create_link():
    conn = db.get_db()
    f = request.form
    try:
        target = validated("target", resolve.validate_url, f.get("target", ""))
        expires = parse_expiry(f.get("expires_at", ""))
        kind, plan = slug_plan(f)
        for _ in range(20 if kind == "generate" else 1):
            slug = plan if kind == "custom" else random_slug(*plan)
            if kind == "generate" and (slug in reserved_slugs() or not slug.strip(".")):
                continue
            try:
                conn.execute(
                    "INSERT INTO links(slug, target, created_by, created_at, expires_at) VALUES(?,?,?,?,?)",
                    (slug, target, g.user["username"], db.now_iso(), expires))
                conn.commit()
                flash(f"{base_url()}{slug}", "link")  # the template adds the wording and the open/copy icons
                return redirect(url_for("admin.index"))
            except sqlite3.IntegrityError:
                if kind == "custom":
                    raise resolve.ValidationError(f"Slug ‹{slug}› is already taken.", "slug")
        raise resolve.ValidationError("No free slug found. Use a longer length or a bigger alphabet.", "length")
    except resolve.ValidationError as exc:
        # Show the form again with everything the user typed, and the error inside it.
        return render_index(form=f, error=str(exc), error_field=exc.field), 400

@bp.post("/links/<int:link_id>/toggle")
def toggle_link(link_id):
    own_or_admin(link_id)
    conn = db.get_db()
    conn.execute("UPDATE links SET enabled = 1 - enabled WHERE id = ?", (link_id,))
    conn.commit()
    return back()

def _same_target_key(url: str):
    """Two addresses that differ only in letter case of scheme/host or in a trailing slash count as the same."""
    parts = urlsplit(url.strip())
    return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", parts.query, parts.fragment)

@bp.get("/links/lookup")
def lookup_target():
    """Which links already point to this address? Slugs are only revealed for links the user may see."""
    url = request.args.get("target", "").strip()
    exclude = request.args.get("exclude", type=int)            # the link being edited doesn't count
    try:
        resolve.validate_url(url)
    except resolve.ValidationError:
        return jsonify(count=0, slugs=[])
    want = _same_target_key(url)
    rows = db.get_db().execute("SELECT id, slug, target, created_by FROM links ORDER BY created_at, id").fetchall()
    hits = [r for r in rows if r["id"] != exclude and _same_target_key(r["target"]) == want]
    mine = [r["slug"] for r in hits if g.user["is_admin"] or r["created_by"] == g.user["username"]]
    resp = jsonify(count=len(hits), slugs=mine)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@bp.post("/links/<int:link_id>/update")
def update_link(link_id):
    """Change the target, the slug and the expiry of a link in one go."""
    row = own_or_admin(link_id)
    f = request.form
    try:
        target = validated("target", resolve.validate_url, f.get("target", ""))
        slug = f.get("slug", "").strip()
        validated("slug", resolve.validate_slug, slug)
        if slug != row["slug"] and slug in reserved_slugs():
            raise resolve.ValidationError(f"‹{slug}› is reserved.", "slug")
        expires = parse_expiry(f.get("expires_at", ""))
        conn = db.get_db()
        try:
            conn.execute("UPDATE links SET target = ?, slug = ?, expires_at = ? WHERE id = ?",
                         (target, slug, expires, link_id))
            conn.commit()
        except sqlite3.IntegrityError:
            raise resolve.ValidationError(f"Slug ‹{slug}› is already taken.", "slug")
    except resolve.ValidationError as exc:
        flash(str(exc), f"link:{link_id}:error")        # shown in that link's details, next to the fields
        return back()

    changes = []                                         # [label, value]: the template shows the value after the label
    if slug != row["slug"]:
        changes.append(["new slug", ""])
    if target != row["target"]:
        changes.append(["new target", target])
    if expires != row["expires_at"]:
        changes.append(["expires", expires[:10]] if expires else ["no expiry", ""])
    flash(json.dumps({"slug": slug, "changes": changes}), f"link:{link_id}")
    return back()

@bp.post("/links/<int:link_id>/delete")
def delete_link(link_id):
    own_or_admin(link_id)
    conn = db.get_db()
    conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    conn.commit()
    return back()
