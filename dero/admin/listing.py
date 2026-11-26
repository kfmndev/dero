"""Building the links page: sorting, columns, the search query and the template's data."""

from flask import current_app, g, render_template, request, url_for

from .. import db, query
from ..forms import ALPHABETS, DEFAULT_LENGTH, MAX_LENGTH, MIN_LENGTH, reserved_slugs
from ..urls import base_url

# column -> SQL used for ORDER BY (the keys are the only values ever put into the query)
SORTS = {
    "created": "created_at",
    "slug": "slug COLLATE NOCASE",
    "target": "target COLLATE NOCASE",
    "creator": "created_by COLLATE NOCASE",
    "expires": "expires_at IS NULL, expires_at",
    "visits": "visits",
}

STATUS_LABELS = {"active": "Active", "disabled": "Disabled", "expired": "Expired"}

# (sort key, direction) -> label for the "Sort by" dropdown
ORDER_LABELS = {
    ("created", "desc"): "Newest first",
    ("created", "asc"): "Oldest first",
    ("visits", "desc"): "Most visits",
    ("visits", "asc"): "Fewest visits",
    ("slug", "asc"): "Slug A–Z",
    ("slug", "desc"): "Slug Z–A",
    ("target", "asc"): "Target A–Z",
    ("target", "desc"): "Target Z–A",
    ("expires", "asc"): "Expiring soonest",
    ("expires", "desc"): "Expiring latest",
    ("creator", "asc"): "Creator A–Z",
    ("creator", "desc"): "Creator Z–A",
}

COLUMNS = [
    ("slug", "Slug"),
    ("target", "Target"),
    ("creator", "Created by"),
    ("created", "Created"),
    ("expires", "Expires"),
    ("visits", "Visits"),
]

DEFAULT_COLUMNS = ["slug", "target", "visits"]


def _visible_columns() -> list:
    """The data columns to show, in table order. Chosen in the browser, remembered in the dero_cols cookie."""
    raw = request.cookies.get("dero_cols")

    if raw is None:
        return list(DEFAULT_COLUMNS)
    wanted = set(raw.split(","))

    return [key for key, _ in COLUMNS if key in wanted] or list(DEFAULT_COLUMNS)  # never an empty table


def _effective_query(args, is_admin: bool) -> str:
    """The query text: `q`, plus the older separate parameters (status, owner, order, sort, dir)
    if a URL still has them."""
    text = args.get("q", "").strip()[:500]
    status = args.get("status", "")

    if status in query.STATUSES:
        text = query.add_term(text, f"status={status}")
    owner = args.get("owner", "").strip()

    if owner and is_admin:
        text = query.add_term(text, "created_by=" + query.quote_value(owner))
    key, _, direction = args.get("order", "").partition(":")

    if not (key in query.SORT_KEYS and direction in ("asc", "desc")):
        key, direction = args.get("sort", ""), "asc" if args.get("dir") == "asc" else "desc"

    if key in query.SORT_KEYS and (args.get("order") or args.get("sort")):
        text = query.with_sort(text, key, (direction == "desc") != query.DESC_BY_DEFAULT[key])

    return text


def _slug_source_of(form) -> str:
    """Which "Short link" option a (rejected) form was using."""

    if form.get("slug_source") in ("default", "letters", "chars", "slug"):
        return form["slug_source"]
    if form.get("slug_mode") == "custom" or (not form.get("slug_mode") and form.get("slug")):
        return "slug"

    return {"letters": "letters", "custom": "chars"}.get(form.get("alphabet", ""), "default")


def _own_scope(is_admin):
    """(SQL, arguments) that limit a query to what the user may see: everything for an admin, else their own links."""
    return ("", ()) if is_admin else (" WHERE created_by = ?", (g.user["username"],))


def _find_links(conn, parsed, sort_key, direction, is_admin):
    where, args = [], []

    if not is_admin:  # whatever the query says, people only ever see their own links
        where.append("created_by = ?")
        args.append(g.user["username"])

    if parsed.where:
        where.append(parsed.where)
        args += parsed.params
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    order = f"{SORTS[sort_key]} {direction.upper()}, id DESC"

    return conn.execute(f"SELECT * FROM links{clause} ORDER BY {order}", args).fetchall()


def _creators(conn, is_admin):
    """Everyone who has made a link (for the Created by dropdown); only admins see others."""

    if not is_admin:
        return []

    return [r[0] for r in conn.execute("SELECT DISTINCT created_by FROM links ORDER BY created_by COLLATE NOCASE")]


def _sort_options(is_admin):
    """The entries of the Sort by dropdown: (value, label)."""
    options = []

    for key, desc_by_default in query.DESC_BY_DEFAULT.items():
        if key == "creator" and not is_admin:
            continue

        for reverse in (False, True):
            label = ORDER_LABELS[(key, "desc" if desc_by_default != reverse else "asc")]
            options.append((query.sort_value(key, reverse), label))

    return options


def render_index(form=None, error=None, error_field=None):
    conn = db.get_db()
    is_admin = g.user["is_admin"]
    text = _effective_query(request.args, is_admin)
    now = db.now_iso()
    parsed = query.parse(text, now)
    sort_key, reverse = parsed.sort or ("created", False)
    direction = "desc" if query.DESC_BY_DEFAULT[sort_key] != reverse else "asc"
    links = _find_links(conn, parsed, sort_key, direction, is_admin)
    scope, scope_args = _own_scope(is_admin)
    overall = conn.execute(f"SELECT COUNT(*) FROM links{scope}", scope_args).fetchone()[0]

    def sort_url(key):
        q = query.with_sort(text, key, (not reverse) if key == sort_key else False)

        return url_for("admin.index", q=q) if q else url_for("admin.index")

    return render_template(
        "index.html",
        links=links,
        total=sum(link["visits"] for link in links),
        overall=overall,
        base=base_url(),
        query=text,
        problems=parsed.problems,
        owners=_creators(conn, is_admin),
        statuses=[(v, STATUS_LABELS[v]) for v in query.STATUSES],
        sort_options=_sort_options(is_admin),
        sort_value=query.sort_value(sort_key, reverse),
        sort_keys=list(query.SORT_KEYS),
        sort_defaults=query.DESC_BY_DEFAULT,
        sort=sort_key,
        direction=direction,
        sort_url=sort_url,
        now=now,
        cols=_visible_columns(),
        default_cols=DEFAULT_COLUMNS,
        column_choices=COLUMNS,
        column_labels=dict(COLUMNS),
        admin_path=current_app.config["ADMIN_PATH"],
        filtered=bool(parsed.where),
        back=request.full_path.rstrip("?") if request.method == "GET" else url_for("admin.index"),
        form=form or {},
        error=error,
        error_field=error_field,
        slug_source=_slug_source_of(form or {}),
        alphabets=ALPHABETS,
        default_length=DEFAULT_LENGTH,
        length_range=(MIN_LENGTH, MAX_LENGTH),
        reserved=sorted(reserved_slugs()),
    )
