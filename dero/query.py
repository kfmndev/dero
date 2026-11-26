"""The search language of the links table.

    foo "exact phrase"        free text: searches slug, target and creator (anywhere in them)
    status=expired,disabled   created_by=julian   slug=abc   target=github
                              (a comma means "or" within one key; status and created_by match exactly,
                               slug and target match parts)
    slug=abc*  target=*.pdf   a * stands for any text; with a * the whole value must match, so abc* is "starts with"
                              and *.pdf is "ends with" (also created_by=ann*)
    slug==abc                 exactly this (no parts, no wildcards)
    created=2026-11           expires<2027-01-01    dates: a year, month or day; < <= > >= compare; dates are UTC
                              created>-7d  expires<30d   relative to today: today, yesterday, tomorrow, or a number of
                              days, weeks, months or years (d w m y), - for the past: -7d, 2w, -1y
    expires                   links that expire at all (short for expires!=never)
                              expires=never         links that never expire (also: expires=none, !expires)
    visits>100  visits=0      the visit counter: a number, with < <= > >= and = !=
    sort_by=visits            sort: the key's usual order (newest and most first for created and visits, A-Z for the
                              rest); -visits is descending and +visits ascending (write %2B for a + in an address)
    !term   key!=value        negate
    and  &&   or  ||   ( )    combine and group
    created_by="Anna Maria"   quotes for values with spaces

Terms next to each other are joined with "and"; "and" binds tighter than "or".
The names are the dropdowns' names in snake case (status, created_by, sort_by); creator, owner, by, sortby, sort and
order are older spellings that still work. Unknown keys are plain text (so `a=b` or a pasted URL just searches for
that text); a known key with an operator it does not have (`slug>abc`) matches nothing and is reported.

The browser has a tokenizer with the same rules (static/js/search-language.js, parseQuery) for highlighting
and for keeping the dropdowns in sync; this module is the authority that actually filters.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

# each key (the name used in the code) with every spelling that is accepted for it; the first spelling is the
# dropdown's name in snake case, the others are older ones
KEY_ALIASES = {
    "status": ("status",),
    "creator": ("created_by", "creator", "owner", "by"),
    "slug": ("slug",),
    "target": ("target",),
    "created": ("created",),
    "expires": ("expires",),
    "visits": ("visits",),
    "sortby": ("sort_by", "sortby", "sort", "order"),
}
KEYS = {alias: key for key, aliases in KEY_ALIASES.items() for alias in aliases}  # spelling -> key
STATUSES = ("active", "disabled", "expired")
SORT_KEYS = ("created", "visits", "slug", "target", "creator", "expires")
SORT_ALIASES = {"created_by": "creator"}  # sort_by=created_by, like the key and the dropdown
# keys whose usual order is newest/most first; the others start at A (or soonest)
DESC_BY_DEFAULT = {"created": True, "visits": True, "slug": False, "target": False, "creator": False, "expires": False}

DATE_COLUMNS = {"created": "created_at", "expires": "expires_at"}
# keys that can be unset (a NULL column): the bare key means "is set", and a date comparison never matches an unset one
OPTIONAL_KEYS = {"expires"}
COMPARISONS = ("<=", ">=", "<", ">")  # for dates and visits, written without "=": expires<2027, visits>=100
_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_RELATIVE = re.compile(r"^([+-]?)(\d{1,4})([dwmy])$")  # -7d, 2w, +1y (no sign = ahead)
_RELATIVE_WORDS = {"yesterday": -1, "today": 0, "tomorrow": 1}
_NUMBER = re.compile(r"^\d{1,12}$", re.ASCII)
_KEYED = re.compile(r"^([A-Za-z_]+)(!=|==|<=|>=|=|<|>)(.*)$", re.S)

# the operators each key understands ("!=" is "=" negated, so it is listed as "="); "==" is the exact match
_EQUALITY = ("=", "==")
ALLOWED_OPS = {
    "status": _EQUALITY,
    "creator": _EQUALITY,
    "slug": _EQUALITY,
    "target": _EQUALITY,
    "created": _EQUALITY + COMPARISONS,
    "expires": _EQUALITY + COMPARISONS,
    "visits": _EQUALITY + COMPARISONS,
    "sortby": ("=",),
}


@dataclass
class Tok:
    """One piece of the query text: where it starts and ends, and what it is."""

    kind: str  # ws, lpar, rpar, and, or, not, term
    start: int
    end: int
    key: str | None = None  # canonical key of a keyed term, else None (free text)
    negated: bool = False  # key!=value
    values: tuple[str, ...] = ()
    op: str = (
        "="  # "=" ("!=" is this with negated), "==", one of COMPARISONS, or "set" for a bare optional key (expires)
    )


@dataclass
class Parsed:
    """A query turned into SQL: the WHERE part, its parameters, the sort and any problems found."""

    where: str | None = None  # SQL for the filter part, None = no filter
    params: list[Any] = field(default_factory=list)
    sort: tuple[str, bool] | None = None  # (key, reverse) or None
    problems: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ tokenizer
def _unquote(text: str) -> str:
    """The text without the quotes around it (an unclosed quote is dropped too)."""
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]

    return text[1:] if text.startswith('"') else text


def _split_values(rest: str) -> tuple[str, ...]:
    """a,b,"c d" -> ("a", "b", "c d"); commas inside quotes stay."""
    parts, buf, quoted = [], "", False

    for ch in rest:
        if ch == '"':
            quoted = not quoted
            buf += ch
        elif ch == "," and not quoted:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)

    return tuple(v for v in (_unquote(p) for p in parts) if v != "")


_SYMBOLS = (("(", "lpar"), (")", "rpar"), ("&&", "and"), ("||", "or"), ("!", "not"))


def _word_end(text: str, i: int) -> int:
    """Where the word that starts at i ends: at whitespace or a parenthesis (a quoted part may hold both)."""
    j, n = i, len(text)

    while j < n and not text[j].isspace() and text[j] not in "()":
        if text[j] == '"':
            k = text.find('"', j + 1)
            j = n if k == -1 else k + 1
        else:
            j += 1

    return j


def _word_token(text: str, i: int, j: int) -> Tok:
    """The word text[i:j] is "and", "or", a key=value term or free text."""
    word = text[i:j]
    lower = word.lower()

    if lower in ("and", "or"):
        return Tok(lower, i, j)

    if lower in OPTIONAL_KEYS:
        return Tok("term", i, j, lower, False, (), "set")
    m = _KEYED.match(word)

    if m and (key := KEYS.get(m.group(1).lower())):
        op = m.group(2)

        return Tok("term", i, j, key, op == "!=", _split_values(m.group(3)), "=" if op == "!=" else op)

    return Tok("term", i, j, None, False, (_unquote(word),))


def tokenize(text: str) -> list[Tok]:
    """Cut the query into tokens: spaces, parentheses, and/or/not and terms. The tokens cover the whole text."""
    toks, i, n = [], 0, len(text)

    while i < n:
        if text[i].isspace():
            j = i

            while j < n and text[j].isspace():
                j += 1
            toks.append(Tok("ws", i, j))
            i = j
            continue

        for symbol, kind in _SYMBOLS:
            if text.startswith(symbol, i):
                toks.append(Tok(kind, i, i + len(symbol)))
                i += len(symbol)
                break
        else:
            j = _word_end(text, i)
            toks.append(_word_token(text, i, j))
            i = j

    return toks


# ------------------------------------------------------------------ parser: tokens -> tree
Node = tuple[
    Any, ...
]  # a node of the parsed query: ("text", t), ("kv", key, values, op), ("not", n), ("and"|"or", [n])
NOOP: Node = ("noop",)  # nothing to filter by


class _Parser:
    """Turns the tokens into a tree of nodes ('and' binds tighter than 'or'); problems are collected, not raised."""

    def __init__(self, toks: list[Tok]) -> None:
        """Start at the first token (spaces are ignored)."""
        self.toks = [t for t in toks if t.kind != "ws"]
        self.i = 0
        self.sort = None
        self.problems = []

    def kind(self) -> str | None:
        """The kind of the current token, or None at the end."""
        return self.toks[self.i].kind if self.i < len(self.toks) else None

    def parse(self) -> Node:
        """The whole query as one node (the NOOP node if there is nothing to filter by)."""
        nodes = [self.or_expr()]

        while self.i < len(self.toks):  # only reachable on a stray ")"
            self.problems.append("Unbalanced )")
            self.i += 1
            nodes.append(self.or_expr())

        return self._join("and", nodes)

    @staticmethod
    def _join(op: str, nodes: list[Node]) -> Node:
        """Combine nodes with and/or; NOOP nodes vanish, and one node stays as it is."""
        nodes = [n for n in nodes if n != NOOP]

        if not nodes:
            return NOOP

        return nodes[0] if len(nodes) == 1 else (op, nodes)

    def or_expr(self) -> Node:
        """Parts joined by 'or'."""
        parts = [self.and_expr()]

        while self.kind() == "or":
            self.i += 1
            parts.append(self.and_expr())

        return self._join("or", parts)

    def and_expr(self) -> Node:
        """Parts next to each other or joined by 'and'."""
        parts = []

        while True:
            k = self.kind()

            if k == "and":
                self.i += 1
            elif k in (None, "or", "rpar"):
                break
            else:
                parts.append(self.unary())

        return self._join("and", parts)

    def unary(self) -> Node:
        """A term, a group, or either of them negated with '!'."""
        if self.kind() == "not":
            self.i += 1

            if self.kind() in (None, "or", "and", "rpar"):
                return NOOP  # a dangling "!"
            inner = self.unary()

            return NOOP if inner == NOOP else ("not", inner)

        return self.primary()

    def _read_sort(self, tok: Tok) -> None:
        """sort_by=visits / -visits / +visits: remember the sort, or report one that does not exist."""

        if not tok.values:
            return
        raw = tok.values[0]
        sign = raw[0] if raw[0] in "+-" else ""
        name = raw[len(sign) :].lower()
        name = SORT_ALIASES.get(name, name)

        if tok.op not in ALLOWED_OPS["sortby"]:
            self.problems.append(f"sort_by does not support {tok.op}")
        elif name in SORT_KEYS:
            # stored as "the key's usual order, reversed or not": a sign only reverses it if it asks for the other way
            self.sort = (name, bool(sign) and (sign == "-") != DESC_BY_DEFAULT[name])
        else:
            self.problems.append(f"Unknown sort: {raw}")

    def primary(self) -> Node:
        """A parenthesised group, a free-text word or a key=value term."""
        tok = self.toks[self.i]
        self.i += 1

        if tok.kind == "lpar":
            node = self.or_expr()

            if self.kind() == "rpar":
                self.i += 1
            else:
                self.problems.append("Missing )")

            return node

        if tok.kind != "term":  # cannot happen (and/or/rpar are handled by the callers)
            return NOOP
        if tok.key is None:
            return ("text", tok.values[0])

        if tok.key == "sortby":
            self._read_sort(tok)

            return NOOP  # a directive, not a filter (and never negated)

        if not tok.values and tok.op != "set":
            return NOOP
        node = ("kv", tok.key, tok.values, tok.op)

        return ("not", node) if tok.negated else node


# ------------------------------------------------------------------ tree -> SQL
_STATUS_SQL = {
    "active": ("(enabled = 1 AND (expires_at IS NULL OR expires_at > ?))", True),
    "disabled": ("(enabled = 0)", False),
    "expired": ("(expires_at IS NOT NULL AND expires_at <= ?)", True),
}


def _add_months(day: date, months: int) -> date:
    """The day this many months later (earlier if negative); the 31st becomes the last day of a shorter month."""
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1

    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def _relative_day(value: str, today: date) -> str | None:
    """today / yesterday / tomorrow / -7d / 2w / 3m / -1y as an ISO day, or None if the value is not of that form."""
    word = value.lower()

    if word in _RELATIVE_WORDS:
        return (today + timedelta(days=_RELATIVE_WORDS[word])).isoformat()
    m = _RELATIVE.match(word)

    if not m:
        return None
    amount, unit = int(m.group(2)) * (-1 if m.group(1) == "-" else 1), m.group(3)

    try:
        if unit == "d":
            day = today + timedelta(days=amount)
        elif unit == "w":
            day = today + timedelta(weeks=amount)
        else:
            day = _add_months(today, amount * (12 if unit == "y" else 1))
    except (OverflowError, ValueError):
        return None

    return day.isoformat()


def _date_condition(key: str, op: str, value: str, today: date, params: list[Any], problems: list[str]) -> str:
    """created=2026 / created>=2026-11 / expires<2027-01-01 / created>-7d / expires=never. Dates are UTC.
    The stored times are ISO strings, so comparing their first 4, 7 or 10 characters compares years, months or days.
    A link without an expiry matches no date, so `!expires<2027` (not expiring before 2027) still includes it."""
    column = DATE_COLUMNS[key]
    value = value.strip()
    op = "=" if op == "==" else op

    if key in OPTIONAL_KEYS and op == "=" and value.lower() in ("none", "never"):
        return f"{column} IS NULL"

    if text := _relative_day(value, today):
        pass
    elif (m := _DATE.match(value)) and _real_date(m):
        year, month, day = m.groups()
        text = year + (f"-{month}" if month else "") + (f"-{day}" if day else "")
    else:
        problems.append(f"Unknown date: {value}")
        return "0"
    params.append(text)
    compare = f"substr({column}, 1, {len(text)}) {op} ?"

    return f"({column} IS NOT NULL AND {compare})" if key in OPTIONAL_KEYS else compare


def _real_date(m: re.Match[str]) -> bool:
    """Whether a matched year[-month[-day]] is a date that exists (no month 13, no 30 February)."""
    try:
        datetime(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1))
    except ValueError:
        return False

    return True


def _escaped(text: str) -> str:
    """The text with LIKE's own characters (% _ and the escape) made literal."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like(term: str) -> str:
    """A LIKE pattern that finds the term anywhere (its own % and _ are matched literally)."""
    return "%" + _escaped(term) + "%"


def glob_like(value: str) -> str:
    """A LIKE pattern for a value with * in it: each * is any text, the rest is literal, and all of it must match."""
    return "%".join(_escaped(part) for part in value.split("*"))


def _compile_status(values: tuple[str, ...], now: str, params: list[Any], problems: list[str]) -> str:
    """SQL for status=a,b: the statuses are alternatives."""
    parts = []

    for v in values:
        sql, needs_now = _STATUS_SQL.get(v.lower(), (None, False))

        if sql is None:
            problems.append(f"Unknown status: {v}")
            parts.append("0")
            continue
        parts.append(sql)

        if needs_now:
            params.append(now)

    return "(" + " OR ".join(parts) + ")"


def _number_condition(column: str, op: str, value: str, params: list[Any], problems: list[str]) -> str:
    """visits=0 / visits>100: a whole number compared with the column."""

    if not _NUMBER.match(value):
        problems.append(f"Unknown number: {value}")
        return "0"
    params.append(int(value))

    return f"{column} {'=' if op == '==' else op} ?"


def _text_condition(column: str, op: str, value: str, exact: bool, params: list[Any]) -> str:
    """slug=abc (contains) / slug=abc* (a * is any text, the whole value must match) / slug==abc (exactly).
    `exact` is for columns whose plain = is an exact match already (created_by); all of it ignores upper/lower case."""

    if op == "==" or (exact and "*" not in value):
        params.append(value.lower())

        return f"lower({column}) = ?"
    params.append(glob_like(value) if "*" in value else like(value))

    return f"{column} LIKE ? ESCAPE '\\'"


def _compile_term(key: str, values: tuple[str, ...], op: str, now: str, params: list[Any], problems: list[str]) -> str:
    """One key=value term (values are alternatives)."""

    if op != "set" and op not in ALLOWED_OPS[key]:
        problems.append(f"{key} does not support {op}")

        return "0"

    if op == "set":
        return f"({DATE_COLUMNS[key]} IS NOT NULL)"

    if key == "status":
        return _compile_status(values, now, params, problems)

    if key in DATE_COLUMNS:
        today = date.fromisoformat(now[:10])

        return "(" + " OR ".join(_date_condition(key, op, v, today, params, problems) for v in values) + ")"

    if key == "visits":
        return "(" + " OR ".join(_number_condition("visits", op, v, params, problems) for v in values) + ")"
    column = {"creator": "created_by"}.get(key, key)  # slug or target, or the creator
    exact = key == "creator"

    return "(" + " OR ".join(_text_condition(column, op, v, exact, params) for v in values) + ")"


def _compile(node: Node, now: str, params: list[Any], problems: list[str]) -> str:
    """SQL for a node; values go into `params` and are never put into the SQL text."""
    kind = node[0]

    if kind == "text":
        params += [like(node[1])] * 3

        return "(slug LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\' OR created_by LIKE ? ESCAPE '\\')"

    if kind == "kv":
        return _compile_term(node[1], node[2], node[3], now, params, problems)

    if kind == "not":
        return "(NOT " + _compile(node[1], now, params, problems) + ")"
    joiner = " AND " if kind == "and" else " OR "

    return "(" + joiner.join(_compile(n, now, params, problems) for n in node[1]) + ")"


def parse(text: str, now: str) -> Parsed:
    """Turn a query into SQL (parameters are always bound, never interpolated)."""
    parser = _Parser(tokenize(text))
    tree = parser.parse() if parser.toks else NOOP
    out = Parsed(sort=parser.sort, problems=list(parser.problems))

    if tree != NOOP:
        out.where = _compile(tree, now, out.params, out.problems)
    out.problems = list(dict.fromkeys(out.problems))

    return out


# ------------------------------------------------------------------ editing queries as text (sort links, legacy URLs)
def sort_value(key: str, reverse: bool) -> str:
    """What follows `sort_by=` for a sort, or "" for the default (newest first): the key alone is its usual order,
    and a sign only where it is the other direction (`+visits` is fewest first, `-slug` is Z to A)."""

    if key == "created" and not reverse:
        return ""

    if not reverse:
        return key

    return ("+" if DESC_BY_DEFAULT[key] else "-") + key


def sort_term(key: str, reverse: bool) -> str:
    """The whole sort_by term for a sort, or "" for the default."""
    value = sort_value(key, reverse)
    return f"sort_by={value}" if value else ""


def _remove(text: str, toks: list[Tok]) -> str:
    """The text without these tokens and the space after each (or before the last, at the end)."""
    for t in sorted(toks, key=lambda t: t.start, reverse=True):
        end = t.end

        while end < len(text) and text[end].isspace():
            end += 1
        start = t.start

        if end == len(text):  # at the end: take the whitespace before it instead
            while start > 0 and text[start - 1].isspace():
                start -= 1
        text = text[:start] + text[end:]

    return text.strip()


def has_top_level_or(toks: list[Tok]) -> bool:
    """Whether an 'or' stands outside every parenthesis."""
    depth = 0

    for t in toks:
        if t.kind == "lpar":
            depth += 1
        elif t.kind == "rpar":
            depth = max(0, depth - 1)
        elif t.kind == "or" and depth == 0:
            return True

    return False


def add_term(text: str, term: str) -> str:
    """Append a term that must hold in addition to everything else."""
    text = text.strip()

    if not text:
        return term

    return f"({text}) {term}" if has_top_level_or(tokenize(text)) else f"{text} {term}"


def with_sort(text: str, key: str, reverse: bool) -> str:
    """The query with its sort_by term replaced by this sort (the default sort has no term)."""
    toks = [t for t in tokenize(text) if t.kind == "term" and t.key == "sortby"]
    base = _remove(text, toks)
    term = sort_term(key, reverse)

    return f"{base} {term}".strip() if term else base


def quote_value(value: str) -> str:
    """The value in quotes if it holds spaces, parentheses or quotes (quotes inside are dropped)."""
    return '"' + value.replace('"', "") + '"' if (not value or re.search(r'[\s()"]', value)) else value
