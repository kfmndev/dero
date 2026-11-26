"""Reading what the New link and edit forms send: slugs (typed or generated), expiry dates, validation errors."""

import secrets
from datetime import datetime

from flask import current_app

from . import resolve

# Alphabets slugs can be generated from. "default" leaves out look-alikes (i, l, o, 0, 1).
ALPHABETS = {
    "default": "abcdefghjkmnpqrstuvwxyz23456789",
    "letters": "abcdefghijklmnopqrstuvwxyz",
}

SLUG_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-")

MIN_LENGTH, MAX_LENGTH, DEFAULT_LENGTH = 3, 32, 5


def _quoted(chars: str) -> str:
    """The offending characters for a message: '|'  or  '|' and '?'  or  '|', '?' and '#'.
    A space is named, since it is invisible. More than six are cut: '|', '?', '#', '%', '"', '<', …"""
    shown = ["space" if c == " " else f"'{c}'" for c in chars[:6]]

    if len(chars) > 6:
        return ", ".join(shown) + ", …"

    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def random_slug(alphabet: str, length: int) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def slug_plan(f):
    """Read the slug part of the form. Returns ("custom", slug) or ("generate", (alphabet, length)).

    slug_source is one of: default, letters (random from that alphabet), chars (random from the characters in
    alphabet_custom, where a repeated character is more likely), slug (use the typed slug).
    Older posts without it: slug_mode/alphabet are read, and a given slug is used, otherwise one is generated.
    """
    source = f.get("slug_source", "")
    slug = f.get("slug", "").strip()

    if not source:
        mode, name = f.get("slug_mode", ""), f.get("alphabet", "default") or "default"

        if mode == "custom" or (mode == "" and slug):
            source = "slug"
        elif name == "custom":
            source = "chars"
        elif name in ALPHABETS:
            source = name
        else:
            raise resolve.ValidationError("Unknown alphabet.", "slug_source")

    if source == "slug":
        if not slug:
            raise resolve.ValidationError("Enter a slug, or pick a random one.", "slug")
        validated("slug", resolve.validate_slug, slug)

        if slug in reserved_slugs():
            raise resolve.ValidationError(f"‹{slug}› is reserved.", "slug")

        return "custom", slug

    if source == "chars":
        chars = f.get("alphabet_custom", "")  # duplicates stay: they make a character more likely
        bad = "".join(dict.fromkeys(c for c in chars if c not in SLUG_CHARS))

        if bad:
            raise resolve.ValidationError(
                f"Characters: {_quoted(bad)} can't be used. Allowed are letters, digits and - _ . ~", "alphabet_custom"
            )
        if len(set(chars)) < 2:
            raise resolve.ValidationError("Characters: use at least 2 different ones.", "alphabet_custom")
        alphabet = chars
    elif source in ALPHABETS:
        alphabet = ALPHABETS[source]
    else:
        raise resolve.ValidationError("Unknown option.", "slug_source")

    try:
        length = int(f.get("length") or DEFAULT_LENGTH)
    except ValueError:
        length = 0

    if not MIN_LENGTH <= length <= MAX_LENGTH:
        raise resolve.ValidationError(f"Length must be between {MIN_LENGTH} and {MAX_LENGTH}.", "length")

    return "generate", (alphabet, length)


def reserved_slugs():
    return {current_app.config["ADMIN_PATH"].strip("/").split("/")[0], "static"}


def parse_expiry(text: str):
    """'' -> None (never expires); 'YYYY-MM-DD' -> end of that day (UTC). A past day is allowed (the page warns)."""
    text = (text or "").strip()

    if not text:
        return None

    try:
        day = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise resolve.ValidationError("Expiry must be a date (YYYY-MM-DD).", "expires_at")

    return day.strftime("%Y-%m-%dT23:59:59Z")


def validated(field, fn, *args):
    """Run a validator and tag its error with the form field it belongs to."""

    try:
        return fn(*args)
    except resolve.ValidationError as exc:
        raise resolve.ValidationError(str(exc), field) from exc
