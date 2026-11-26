"""Live visits: a server-sent-events stream of the visit counters."""

import json
import sqlite3
import time
from collections.abc import Iterator
from typing import Any

from flask import Response, current_app, g

from . import bp

KEEPALIVE_EVERY = 10  # quiet ticks between comments that keep the stream open


def _fingerprint(conn: sqlite3.Connection, where: str, args: tuple[str, ...]) -> tuple[int, int]:
    """One cheap aggregate: how many links, how many visits."""
    return tuple(conn.execute(f"SELECT COUNT(*), COALESCE(SUM(visits), 0) FROM links{where}", args).fetchone())


def _snapshot(conn: sqlite3.Connection, where: str, args: tuple[str, ...]) -> dict[int, tuple[str, int]]:
    """{id: (slug, visits)} of the links in scope."""
    return {r[0]: (r[1], r[2]) for r in conn.execute(f"SELECT id, slug, visits FROM links{where}", args)}


def _increases(known: dict[int, tuple[str, int]], latest: dict[int, tuple[str, int]]) -> list[dict[str, Any]]:
    """The links whose counter went up between two snapshots."""
    return [
        {"id": i, "slug": slug, "visits": visits, "delta": visits - known[i][1]}
        for i, (slug, visits) in latest.items()
        if i in known and visits > known[i][1]
    ]


def _events(path: str, where: str, args: tuple[str, ...], tick: float, max_ticks: int | None) -> Iterator[str]:
    """The text of the event stream. It runs until the page leaves (or, in tests, for max_ticks ticks)."""
    conn = sqlite3.connect(path, timeout=10)

    try:
        seen, known = _fingerprint(conn, where, args), _snapshot(conn, where, args)
        yield "retry: 3000\n: ready\n\n"
        ticks = quiet = 0

        while max_ticks is None or ticks < max_ticks:
            time.sleep(tick)
            ticks += 1
            now = _fingerprint(conn, where, args)

            if now == seen:
                quiet += 1

                if quiet >= KEEPALIVE_EVERY:  # proxies keep the stream open, and a page that left is
                    quiet = 0  # noticed by the failing write
                    yield ": keepalive\n\n"
                continue
            quiet, seen = 0, now
            latest = _snapshot(conn, where, args)

            if set(latest) != set(known):
                yield "event: refresh\ndata: {}\n\n"
            changed = _increases(known, latest)

            if changed:
                yield f"event: visit\ndata: {json.dumps(changed)}\n\n"
            known = latest
    finally:
        conn.close()


@bp.get("/links/visits/stream")
def visit_stream() -> Response:
    """Server-sent events for "Live visits": `visit` when a counter of a link the user may see went up, `refresh` when
    links were created or deleted. Only counters are read, no visit is recorded. Every open stream holds one worker
    thread (gunicorn runs threaded workers) and checks the database itself, so visits handled by any worker show up."""
    where, args = ("", ()) if g.user["is_admin"] else (" WHERE created_by = ?", (g.user["username"],))
    config = current_app.config
    # tests end the stream with LIVE_MAX_TICKS; normally it runs until the page leaves
    stream = _events(config["DATABASE"], where, args, float(config.get("LIVE_TICK", 1.0)), config.get("LIVE_MAX_TICKS"))

    return Response(
        stream, mimetype="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )
