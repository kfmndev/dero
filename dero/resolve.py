"""Turning an incoming path into a redirect target.

Order: exact link -> pattern rules (by priority) -> fallback URL -> 404.
"""

import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlsplit

import regex  # third-party: supports match timeouts, so a bad pattern can't hang us

from .db import get_db, get_setting, now_iso

# the characters a URL path never needs to escape (RFC 3986 "unreserved")
SLUG_RE = re.compile(r"[A-Za-z0-9._~-]{1,64}")
PLACEHOLDER_RE = re.compile(r"\{(\d+)\}")
REGEX_TIMEOUT = 0.05  # seconds


class ValidationError(ValueError):
    """A value the user sent is not acceptable; `field` names the form field the message belongs to."""

    def __init__(self, message: str, field: str | None = None) -> None:
        """Keep the message and the name of the field it is about."""
        super().__init__(message)
        self.field = field  # name of the form field the message belongs to, if any


def validate_slug(slug: str) -> str:
    """The slug, if it only uses URL-safe characters and is not just dots; else a ValidationError."""
    if not SLUG_RE.fullmatch(slug):
        raise ValidationError("A slug can use letters, digits and - _ . ~, up to 64 characters.")
    if not slug.strip("."):
        raise ValidationError(
            "A slug needs at least one character that isn't a dot."
        )  # "/." and "/.." are folded away by browsers

    return slug


def validate_url(url: str) -> str:
    """Plain http(s) URL (no javascript:, data:, ...)."""
    url = url.strip()
    parts = urlsplit(url)

    if parts.scheme not in ("http", "https") or not parts.netloc or len(url) > 2048:
        raise ValidationError("Enter a full web address starting with http:// or https://.")

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
def _compile(pattern: str, match_type: str) -> regex.Pattern[str]:
    """The compiled pattern of a rule (cached)."""
    return regex.compile(glob_to_regex(pattern) if match_type == "glob" else pattern)


def validate_rule(pattern: str, match_type: str, target: str) -> None:
    """Check a new rule: the pattern compiles, its {n} placeholders exist, and the target is a URL."""
    pattern = pattern.strip().strip("/")

    if not pattern or len(pattern) > 255:
        raise ValidationError("Enter a pattern, up to 255 characters.")
    if match_type not in ("glob", "regex"):
        raise ValidationError("Choose glob or regex.")

    try:
        compiled = _compile(pattern, match_type)
    except regex.error as exc:
        raise ValidationError(f"This pattern doesn't work: {exc}") from exc
    indices = [int(n) for n in PLACEHOLDER_RE.findall(target)]

    bad = next((n for n in indices if n < 1 or n > compiled.groups), None)

    if bad is not None:
        captures = {0: "nothing", 1: "only 1 part"}.get(compiled.groups, f"only {compiled.groups} parts")
        raise ValidationError(f"The target uses {{{bad}}}, but the pattern captures {captures}.")
    validate_url(PLACEHOLDER_RE.sub("x", target))


def fill_target(template: str, groups: tuple[str | None, ...]) -> str:
    """Put the captured groups into the target where it says {1}, {2}, ..."""

    def sub(m: re.Match[str]) -> str:
        """The text for one {n} placeholder (empty if the pattern has no such group)."""
        idx = int(m.group(1)) - 1
        return quote(groups[idx] or "", safe="/") if 0 <= idx < len(groups) else ""

    return PLACEHOLDER_RE.sub(sub, template)


def match_rule(rule: Mapping[str, Any], path: str) -> str | None:
    """The target a rule gives for the path, or None if it does not match (or takes too long)."""
    try:
        m = _compile(rule["pattern"], rule["match_type"]).fullmatch(path, timeout=REGEX_TIMEOUT)
    except TimeoutError:
        return None

    return fill_target(rule["target"], m.groups()) if m else None


def resolve(path: str) -> tuple[str | None, bool]:
    """Return (url, was_counted) or (None, False)."""
    db = get_db()
    path = path.strip("/")

    link = db.execute(
        "SELECT id, target FROM links WHERE slug = ? AND enabled = 1 AND (expires_at IS NULL OR expires_at > ?)",
        (path, now_iso()),
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
