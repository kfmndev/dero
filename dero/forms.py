"""Reading what the New link and edit forms send: slugs (typed or generated), expiry dates, validation errors."""

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
    """The offending characters for a message, each in a code box: |  or  | and ?  or  |, ? and #.
    A space is named, since it is invisible. More than six are cut: |, ?, #, %, ", <, …"""
    shown = ["space" if c == " " else f"⟨{c}⟩" for c in chars[:6]]

    if len(chars) > 6:
        return ", ".join(shown) + ", …"

    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def random_slug(alphabet: str, length: int) -> str:
    """A slug of `length` characters drawn at random from the alphabet (a repeated character is more likely)."""
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _slug_source(f: Mapping[str, str], slug: str) -> str:
    """The slug_source of the form. Older posts have slug_mode/alphabet instead:
    a given slug is used, otherwise one is drawn."""
    source = f.get("slug_source", "")

    if source:
        return source
    mode, name = f.get("slug_mode", ""), f.get("alphabet", "default") or "default"

    if mode == "custom" or (mode == "" and slug):
        return "slug"

    if name == "custom":
        return "chars"

    if name in ALPHABETS:
        return name
    raise resolve.ValidationError("Choose one of the listed slug types.", "slug_source")


def _typed_slug(slug: str) -> str:
    """A slug the user typed, if it is allowed and free to use."""
    if not slug:
        raise resolve.ValidationError("Type a slug, or choose a random one.", "slug")
    validated("slug", resolve.validate_slug, slug)

    if slug in reserved_slugs():
        raise resolve.ValidationError(f"‹{slug}› is reserved by dero. Choose another slug.", "slug", "lock")

    return slug


def _own_characters(f: Mapping[str, str]) -> str:
    """The characters a slug is drawn from. Duplicates stay: they make a character more likely."""
    chars = f.get("alphabet_custom", "")
    bad = "".join(dict.fromkeys(c for c in chars if c not in SLUG_CHARS))

    if bad:
        raise resolve.ValidationError(
            f"{_quoted(bad)} can't be used in a slug – use letters, digits or ⟨- _ . ~⟩", "alphabet_custom"
        )

    if len(set(chars)) < 2:
        raise resolve.ValidationError("Use at least 2 different characters.", "alphabet_custom")

    return chars


def _slug_length(f: Mapping[str, str]) -> int:
    """The length of a generated slug (the default if none is given)."""
    try:
        length = int(f.get("length") or DEFAULT_LENGTH)
    except ValueError:
        length = 0

    if not MIN_LENGTH <= length <= MAX_LENGTH:
        raise resolve.ValidationError(f"Length must be {MIN_LENGTH} to {MAX_LENGTH} characters.", "length")

    return length


@dataclass(frozen=True)
class SlugPlan:
    """How a new link gets its slug: the one the user typed, or one drawn at random from an alphabet."""

    typed: str | None = None  # the typed slug; None means one is drawn
    alphabet: str = ""
    length: int = 0


def slug_plan(f: Mapping[str, str]) -> SlugPlan:
    """Read the slug part of the form: a typed slug, or the alphabet and length to draw one with.

    slug_source is one of: default, letters (random from that alphabet), chars (random from the characters in
    alphabet_custom, where a repeated character is more likely), slug (use the typed slug).
    Older posts without it: slug_mode/alphabet are read, and a given slug is used, otherwise one is generated.
    """
    slug = f.get("slug", "").strip()
    source = _slug_source(f, slug)

    if source == "slug":
        return SlugPlan(typed=_typed_slug(slug))

    if source == "chars":
        alphabet = _own_characters(f)
    elif source in ALPHABETS:
        alphabet = ALPHABETS[source]
    else:
        raise resolve.ValidationError("Choose one of the listed slug types.", "slug_source")

    return SlugPlan(alphabet=alphabet, length=_slug_length(f))


def reserved_slugs() -> set[str]:
    """Slugs that would clash with the admin UI or the static files."""
    return {current_app.config["ADMIN_PATH"].strip("/").split("/")[0], "static"}


def parse_expiry(text: str) -> str | None:
    """'' -> None (never expires); 'YYYY-MM-DD' -> end of that day (UTC). A past day is allowed (the page warns)."""
    text = (text or "").strip()

    if not text:
        return None

    try:
        day = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise resolve.ValidationError("Enter the expiry as a date, like ⟨2026-12-31⟩.", "expires_at")

    return day.strftime("%Y-%m-%dT23:59:59Z")


def validated[T](field: str, fn: Callable[..., T], *args: Any) -> T:
    """Run a validator and tag its error with the form field it belongs to."""

    try:
        return fn(*args)
    except resolve.ValidationError as exc:
        raise resolve.ValidationError(str(exc), field, exc.own_icon) from exc
