"""Pattern rules and the fallback address (admins only)."""

from flask import flash, g, redirect, render_template, request, url_for

from .. import auth, db, resolve
from . import bp


# ---- admin only: rules + fallback
@bp.get("/rules")
@auth.admin_required
def rules():
    rows = db.get_db().execute("SELECT * FROM rules ORDER BY priority, id").fetchall()
    return render_template("rules.html", rules=rows, fallback=db.get_setting("fallback_url"))


@bp.post("/rules")
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
        conn.execute(
            "INSERT INTO rules(pattern, match_type, target, priority, created_by, created_at) VALUES(?,?,?,?,?,?)",
            (pattern, mtype, target, priority, g.user["username"], db.now_iso()),
        )
        conn.commit()
    except resolve.ValidationError as exc:
        flash(str(exc), "rules:error")

    return redirect(url_for("admin.rules"))


@bp.post("/rules/<int:rule_id>/priority")
@auth.admin_required
def rule_priority(rule_id):
    try:
        prio = int(request.form.get("priority", ""))
    except ValueError:
        flash("Priority must be a number.", "rules:error")
        return redirect(url_for("admin.rules"))
    conn = db.get_db()
    conn.execute("UPDATE rules SET priority = ? WHERE id = ?", (prio, rule_id))
    conn.commit()

    return redirect(url_for("admin.rules"))


@bp.post("/rules/<int:rule_id>/toggle")
@auth.admin_required
def rule_toggle(rule_id):
    conn = db.get_db()
    conn.execute("UPDATE rules SET enabled = 1 - enabled WHERE id = ?", (rule_id,))
    conn.commit()

    return redirect(url_for("admin.rules"))


@bp.post("/rules/<int:rule_id>/delete")
@auth.admin_required
def rule_delete(rule_id):
    conn = db.get_db()
    conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()

    return redirect(url_for("admin.rules"))


@bp.post("/settings/fallback")
@auth.admin_required
def set_fallback():
    value = request.form.get("fallback_url", "").strip()

    try:
        db.set_setting("fallback_url", resolve.validate_url(value) if value else "")
        flash("Fallback saved." if value else "Fallback cleared.", "fallback")
    except resolve.ValidationError as exc:
        flash(str(exc), "fallback:error")

    return redirect(url_for("admin.rules"))
