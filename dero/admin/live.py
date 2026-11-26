"""Live visits: a server-sent-events stream of the visit counters."""

import json
import sqlite3
import time

from flask import Response, current_app, g

from . import bp


@bp.get("/links/visits/stream")
def visit_stream():
    """Server-sent events for "Live visits": `visit` when a counter of a link the user may see went up, `refresh` when
    links were created or deleted. Only counters are read, no visit is recorded. Every open stream holds one worker
    thread (gunicorn runs threaded workers) and checks the database itself, so visits handled by any worker show up."""
    own = None if g.user["is_admin"] else g.user["username"]
    path = current_app.config["DATABASE"]
    tick = float(current_app.config.get("LIVE_TICK", 1.0))
    max_ticks = current_app.config.get("LIVE_MAX_TICKS")  # tests end the stream; normally it runs until the page leaves
    where, args = ("", ()) if own is None else (" WHERE created_by = ?", (own,))

    def events():
        conn = sqlite3.connect(path, timeout=10)

        try:

            def fingerprint():  # one cheap aggregate: how many links, how many visits
                return tuple(
                    conn.execute(f"SELECT COUNT(*), COALESCE(SUM(visits), 0) FROM links{where}", args).fetchone()
                )

            def snapshot():
                return {r[0]: (r[1], r[2]) for r in conn.execute(f"SELECT id, slug, visits FROM links{where}", args)}

            seen, known = fingerprint(), snapshot()
            yield "retry: 3000\n: ready\n\n"
            ticks = quiet = 0

            while max_ticks is None or ticks < max_ticks:
                time.sleep(tick)
                ticks += 1
                now = fingerprint()

                if now == seen:
                    quiet += 1

                    if quiet >= 10:  # a comment now and then: proxies keep the stream open,
                        quiet = 0  # and a page that left is noticed by the failing write
                        yield ": keepalive\n\n"
                    continue
                quiet, seen = 0, now
                latest = snapshot()

                if set(latest) != set(known):
                    yield "event: refresh\ndata: {}\n\n"
                changed = [
                    {"id": i, "slug": slug, "visits": visits, "delta": visits - known[i][1]}
                    for i, (slug, visits) in latest.items()
                    if i in known and visits > known[i][1]
                ]

                if changed:
                    yield f"event: visit\ndata: {json.dumps(changed)}\n\n"
                known = latest
        finally:
            conn.close()

    return Response(
        events(), mimetype="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )
