"""How slugs and short links are drawn in pages: one coloured, truncated box everywhere (template filters)."""

import json
import re
from itertools import groupby

from flask import Flask
from markupsafe import Markup, escape

from .urls import base_url

SLUG_SHOWN = 20  # longer slugs are cut after this many characters wherever they are only displayed


def highlight_slug(slug: str, limit: int = 0) -> Markup:
    """Colour a slug like Bitwarden colours passwords: digits and symbols stand out, letters stay plain.
    With a limit, a longer slug is cut there and gets an ellipsis (the full slug belongs in a tooltip)."""
    cut = bool(limit) and len(slug) > limit

    if cut:
        slug = slug[:limit]

    def kind(ch: str) -> str:
        """Whether a character is a digit, a letter or a symbol."""
        return "digit" if ch.isdigit() else "letter" if ch.isalpha() else "symbol"

    out: list[str] = []

    for k, chars in groupby(slug, kind):
        text = escape("".join(chars))
        out.append(text if k == "letter" else Markup(f'<span class="hl-{k}">{text}</span>'))

    if cut:
        out.append("…")

    return Markup("").join(out)


def slug_box(slug: str) -> Markup:
    """A slug as it is shown everywhere: in its code box, coloured, cut after SLUG_SHOWN characters
    (the full slug is on hover)."""
    title = Markup(f' title="{escape(slug)}"') if len(slug) > SLUG_SHOWN else Markup("")
    return Markup('<code class="slug"') + title + Markup(">") + highlight_slug(slug, SLUG_SHOWN) + Markup("</code>")


TARGET_TAIL = 12  # characters at the end of a target that stay visible when the middle is cut
TARGET_LAST_PART = 24  # ... or the last part of the path, if it is not longer than this


_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def target_box(url: str) -> Markup:
    """A target as the table shows it: from the domain on (no http:// or https://), in two parts so that the
    stylesheet can cut the middle (the start gets the ellipsis, the end stays). The whole address is on hover."""
    shown = _SCHEME.sub("", url)
    slash = shown.rfind("/")
    cut = slash if 0 < slash and 4 <= len(shown) - slash <= TARGET_LAST_PART else max(0, len(shown) - TARGET_TAIL)
    box = (
        '<span class="url truncate" title="{}">'
        '<span class="target-head"><span>{}</span></span><span class="target-tail">{}</span></span>'
    )

    return Markup(box).format(url, shown[:cut], shown[cut:])


def without_protocol(url: str) -> str:
    """A base address as it is displayed: without http:// or https:// (what is copied or opened keeps it)."""
    return re.sub(r"^https?://", "", url)


def highlight_url(url: str) -> Markup:
    """A short link in one code box: the base address plain, the slug in a box of its own (the only part coloured)."""
    base = base_url()

    if url.startswith(base) and len(url) > len(base):
        return (
            Markup('<code class="urlbox"><span class="base">')
            + escape(without_protocol(base))
            + Markup("</span>")
            + slug_box(url[len(base) :])
            + Markup("</code>")
        )

    return escape(url)


_MARKED = re.compile(r"‹([^›]*)›|⟨([^⟩]*)⟩")
_ICON = re.compile(r"^⟦([a-z-]+)⟧ ?")


def rich(text: str) -> Markup:
    """A message with marked parts: ‹a slug› is shown in its coloured slug box, ⟨anything else⟩ (an example, a pattern,
    a character) in a plain code box. (None of these marks can occur in a slug or in what a user types in the forms.)"""

    def box(m: re.Match[str]) -> str:
        """The box of one marked part."""
        if m.group(1) is not None:
            return str(slug_box(m.group(1)))

        return f"<code>{m.group(2)}</code>"

    return Markup(_MARKED.sub(box, str(escape(text))))


def with_icon(icon: str, text: str) -> str:
    """A message that says which icon its toast shows: the icon goes in front as ⟦name⟧."""
    return f"⟦{icon}⟧ {text}"


def split_icon(message: str) -> tuple[str | None, str]:
    """(icon, text) of a message made with with_icon; the icon is None for a plain message."""
    m = _ICON.match(message)

    return (m.group(1), message[m.end() :]) if m else (None, message)


def register(app: Flask) -> None:
    """Make the filters available to every template."""
    app.add_template_filter(highlight_slug, "hl_slug")
    app.add_template_filter(highlight_url, "hl_url")
    app.add_template_filter(slug_box, "slug_box")
    app.add_template_filter(target_box, "target_box")
    app.add_template_filter(rich, "rich")
    app.add_template_filter(split_icon, "split_icon")
    app.add_template_filter(json.loads, "fromjson")
