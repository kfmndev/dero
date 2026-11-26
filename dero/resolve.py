"""Turning an incoming path into a redirect target.

Order: exact link -> pattern rules (by priority) -> fallback URL -> 404.
"""
import re
from functools import lru_cache
from urllib.parse import quote, urlsplit

import regex  # third-party: supports match timeouts, so a bad pattern can't hang us

from .db import get_db, get_setting, now_iso

SLUG_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
PLACEHOLDER_RE = re.compile(r"\{(\d+)\}")
REGEX_TIMEOUT = 0.05  # seconds


class ValidationError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field  # name of the form field the message belongs to, if any


def validate_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug):
        raise ValidationError("Slug may only contain letters, digits, '-' and '_' (max 64).")
    return slug


def validate_url(url: str) -> str:
    """Plain http(s) URL (no javascript:, data:, ...)."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or len(url) > 2048:
        raise ValidationError("Target must be a valid http:// or https:// URL.")
    return url


def glob_to_regex(pattern: str) -> str:
    """'*' = anything except '/', '**' = anything, '?' = one char. '*' and '**' capture."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append("(.*)")
            i += 2
        elif pattern[i] == "*":
            out.append("([^/]*)")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


@lru_cache(maxsize=256)
def _compile(pattern: str, match_type: str):
    return regex.compile(glob_to_regex(pattern) if match_type == "glob" else pattern)


def validate_rule(pattern: str, match_type: str, target: str) -> None:
    pattern = pattern.strip().strip("/")
    if not pattern or len(pattern) > 255:
        raise ValidationError("Pattern is required (max 255 characters).")
    if match_type not in ("glob", "regex"):
        raise ValidationError("Unknown match type.")
    try:
        compiled = _compile(pattern, match_type)
    except regex.error as exc:
        raise ValidationError(f"Invalid pattern: {exc}") from exc
    indices = [int(n) for n in PLACEHOLDER_RE.findall(target)]
    if any(n < 1 or n > compiled.groups for n in indices):
        raise ValidationError(f"Target uses a placeholder the pattern doesn't capture "
                              f"(pattern has {compiled.groups} group(s)).")
    validate_url(PLACEHOLDER_RE.sub("x", target))


def fill_target(template: str, groups: tuple) -> str:
    def sub(m):
        idx = int(m.group(1)) - 1
        return quote(groups[idx] or "", safe="/") if 0 <= idx < len(groups) else ""
    return PLACEHOLDER_RE.sub(sub, template)


def match_rule(rule, path: str):
    try:
        m = _compile(rule["pattern"], rule["match_type"]).fullmatch(path, timeout=REGEX_TIMEOUT)
    except TimeoutError:
        return None
    return fill_target(rule["target"], m.groups()) if m else None


def resolve(path: str):
    """Return (url, was_counted) or (None, False)."""
    db = get_db()
    path = path.strip("/")

    link = db.execute(
        "SELECT id, target FROM links WHERE slug = ? AND enabled = 1 "
        "AND (expires_at IS NULL OR expires_at > ?)", (path, now_iso())
    ).fetchone()
    if link:
        db.execute("UPDATE links SET visits = visits + 1 WHERE id = ?", (link["id"],))
        db.commit()
        return link["target"], True

    for rule in db.execute("SELECT * FROM rules WHERE enabled = 1 ORDER BY priority, id"):
        url = match_rule(rule, path)
        if url:
            db.execute("UPDATE rules SET visits = visits + 1 WHERE id = ?", (rule["id"],))
            db.commit()
            return url, True

    fallback = get_setting("fallback_url")
    return (fallback or None), False
