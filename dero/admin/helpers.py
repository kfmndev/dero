"""Small helpers the admin routes share."""

from flask import abort, current_app, g, redirect, request, url_for

from .. import db


def back():
    """Return to the page (filters, sorting) a form was submitted from; same-site paths only."""
    back = request.form.get("back", "")

    if back.startswith(current_app.config["ADMIN_PATH"]) and not back.startswith("//") and "\\" not in back:
        return redirect(back)

    return redirect(url_for("admin.index"))


def own_or_admin(link_id):
    row = db.get_db().execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()

    if not row or not (g.user["is_admin"] or row["created_by"] == g.user["username"]):
        abort(404)

    return row
