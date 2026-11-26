"""How slugs and short links are drawn in pages: one coloured, truncated box everywhere (template filters)."""
import json
import re
from itertools import groupby

from markupsafe import Markup, escape

from .urls import base_url

SLUG_SHOWN = 20     # longer slugs are cut after this many characters wherever they are only displayed


def highlight_slug(slug: str, limit: int = 0) -> Markup:
    """Colour a slug like Bitwarden colours passwords: digits and symbols stand out, letters stay plain.
    With a limit, a longer slug is cut there and gets an ellipsis (the full slug belongs in a tooltip)."""
    cut = bool(limit) and len(slug) > limit
    if cut:
        slug = slug[:limit]
    def kind(ch):
        return "digit" if ch.isdigit() else "letter" if ch.isalpha() else "symbol"
    out = []
    for k, chars in groupby(slug, kind):
        text = escape("".join(chars))
        out.append(text if k == "letter" else Markup(f'<span class="hl-{k}">{text}</span>'))
    if cut:
        out.append("…")
    return Markup("").join(out)

def slug_box(slug: str) -> Markup:
    """A slug as it is shown everywhere: in its code box, coloured, cut after SLUG_SHOWN characters (full slug on hover)."""
    title = Markup(f' title="{escape(slug)}"') if len(slug) > SLUG_SHOWN else Markup("")
    return Markup('<code class="slug"') + title + Markup(">") + highlight_slug(slug, SLUG_SHOWN) + Markup("</code>")

def highlight_url(url: str) -> Markup:
    """A short link: the base address in the normal font, the slug in its box."""
    base = base_url()
    if url.startswith(base) and len(url) > len(base):
        return Markup('<span class="base">') + escape(base) + Markup("</span>") + slug_box(url[len(base):])
    return escape(url)

def rich(text: str) -> Markup:
    """A message with ‹slugs› marked: those parts are shown as slugs (a slug can't contain these marks)."""
    return Markup(re.sub(r"‹([^›]*)›", lambda m: str(slug_box(m.group(1))), str(escape(text))))


def register(app):
    """Make the filters and the constant available to every template."""
    app.add_template_filter(highlight_slug, "hl_slug")
    app.add_template_filter(highlight_url, "hl_url")
    app.add_template_filter(slug_box, "slug_box")
    app.add_template_filter(rich, "rich")
    app.add_template_filter(json.loads, "fromjson")
    app.jinja_env.globals["SLUG_SHOWN"] = SLUG_SHOWN
