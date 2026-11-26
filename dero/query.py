"""The search language of the links table.

    foo "exact phrase"        free text: searches slug, target and creator
    status=expired,disabled   created_by=julian   slug=abc   target=github
                              (a comma means "or" within one key; creator and status match exactly,
                               slug and target match parts)
    created=2026-11           expires=<2027-01-01   dates: a year, month or day; < <= > >= compare; dates are UTC
                              expires=none          links that never expire
    sort_by=visits            sort; a leading minus reverses the key's usual order (sort_by=-visits)
    !term   key!=value        negate
    and  &&   or  ||   ( )    combine and group
    created_by="Anna Maria"   quotes for values with spaces

Terms next to each other are joined with "and"; "and" binds tighter than "or".
The names are the dropdowns' names in snake case (status, created_by, sort_by); creator, owner, by, sortby, sort and
order are older spellings that still work. Unknown keys are plain text (so `a=b` or a pasted URL just searches for that text).

The browser has a tokenizer with the same rules (static/app.js, parseQuery) for highlighting and for keeping
the dropdowns in sync; this module is the authority that actually filters.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

KEYS = {
    "status": "status",
    "created_by": "creator", "creator": "creator", "owner": "creator", "by": "creator",       # created_by matches the dropdown
    "slug": "slug", "target": "target",
    "created": "created", "expires": "expires",
    "sort_by": "sortby", "sortby": "sortby", "sort": "sortby", "order": "sortby",             # sort_by matches the dropdown
}
STATUSES = ("active", "disabled", "expired")
SORT_KEYS = ("created", "visits", "slug", "target", "creator", "expires")
# keys whose usual order is newest/most first; the others start at A (or soonest)
DESC_BY_DEFAULT = {"created": True, "visits": True, "slug": False, "target": False, "creator": False, "expires": False}

DATE_COLUMNS = {"created": "created_at", "expires": "expires_at"}
_DATE = re.compile(r"^(<=|>=|<|>)?(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_KEYED = re.compile(r"^([A-Za-z_]+)(!?=)(.*)$", re.S)


@dataclass
class Tok:
    kind: str                       # ws, lpar, rpar, and, or, not, term
    start: int
    end: int
    key: str | None = None          # canonical key of a keyed term, else None (free text)
    negated: bool = False           # key!=value
    values: tuple = ()


@dataclass
class Parsed:
    where: str | None = None        # SQL for the filter part, None = no filter
    params: list = field(default_factory=list)
    sort: tuple | None = None       # (key, reverse) or None
    problems: list = field(default_factory=list)


# ------------------------------------------------------------------ tokenizer
def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text[1:] if text.startswith('"') else text


def _split_values(rest: str) -> tuple:
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


def tokenize(text: str) -> list[Tok]:
    toks, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            toks.append(Tok("ws", i, j))
            i = j
        elif ch in "()":
            toks.append(Tok("lpar" if ch == "(" else "rpar", i, i + 1))
            i += 1
        elif text.startswith("&&", i):
            toks.append(Tok("and", i, i + 2))
            i += 2
        elif text.startswith("||", i):
            toks.append(Tok("or", i, i + 2))
            i += 2
        elif ch == "!":
            toks.append(Tok("not", i, i + 1))
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                if text[j] == '"':                          # a quoted part may hold spaces and parentheses
                    k = text.find('"', j + 1)
                    j = n if k == -1 else k + 1
                else:
                    j += 1
            word = text[i:j]
            lower = word.lower()
            if lower == "and":
                toks.append(Tok("and", i, j))
            elif lower == "or":
                toks.append(Tok("or", i, j))
            else:
                m = _KEYED.match(word)
                key = KEYS.get(m.group(1).lower()) if m else None
                if key:
                    toks.append(Tok("term", i, j, key, m.group(2) == "!=", _split_values(m.group(3))))
                else:
                    toks.append(Tok("term", i, j, None, False, (_unquote(word),)))
            i = j
    return toks


# ------------------------------------------------------------------ parser: tokens -> tree
NOOP = ("noop",)


class _Parser:
    def __init__(self, toks):
        self.toks = [t for t in toks if t.kind != "ws"]
        self.i = 0
        self.sort = None
        self.problems = []

    def kind(self):
        return self.toks[self.i].kind if self.i < len(self.toks) else None

    def parse(self):
        nodes = [self.or_expr()]
        while self.i < len(self.toks):                      # only reachable on a stray ")"
            self.problems.append("Unbalanced )")
            self.i += 1
            nodes.append(self.or_expr())
        return self._join("and", nodes)

    @staticmethod
    def _join(op, nodes):
        nodes = [n for n in nodes if n != NOOP]
        if not nodes:
            return NOOP
        return nodes[0] if len(nodes) == 1 else (op, nodes)

    def or_expr(self):
        parts = [self.and_expr()]
        while self.kind() == "or":
            self.i += 1
            parts.append(self.and_expr())
        return self._join("or", parts)

    def and_expr(self):
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

    def unary(self):
        if self.kind() == "not":
            self.i += 1
            if self.kind() in (None, "or", "and", "rpar"):
                return NOOP                                 # a dangling "!"
            inner = self.unary()
            return NOOP if inner == NOOP else ("not", inner)
        return self.primary()

    def primary(self):
        tok = self.toks[self.i]
        self.i += 1
        if tok.kind == "lpar":
            node = self.or_expr()
            if self.kind() == "rpar":
                self.i += 1
            else:
                self.problems.append("Missing )")
            return node
        if tok.kind != "term":                              # cannot happen (and/or/rpar are handled by the callers)
            return NOOP
        if tok.key is None:
            return ("text", tok.values[0])
        if tok.key == "sortby":
            if tok.values:
                raw = tok.values[0]
                name = raw.lstrip("+-").lower()
                if name in SORT_KEYS:
                    self.sort = (name, raw.startswith("-"))
                else:
                    self.problems.append(f"Unknown sort: {raw}")
            return NOOP                                     # a directive, not a filter (and never negated)
        if not tok.values:
            return NOOP
        node = ("kv", tok.key, tok.values)
        return ("not", node) if tok.negated else node


# ------------------------------------------------------------------ tree -> SQL
_STATUS_SQL = {
    "active": ("(enabled = 1 AND (expires_at IS NULL OR expires_at > ?))", True),
    "disabled": ("(enabled = 0)", False),
    "expired": ("(expires_at IS NOT NULL AND expires_at <= ?)", True),
}


def _date_condition(key: str, value: str, params: list, problems: list) -> str:
    """created=2026 / created=2026-11 / created=2026-11-25 / expires=<2027-01-01 / expires=none. Dates are UTC.
    The stored times are ISO strings, so comparing their first 4, 7 or 10 characters compares years, months or days."""
    column = DATE_COLUMNS[key]
    value = value.strip()
    if key == "expires" and value.lower() in ("none", "never"):
        return f"{column} IS NULL"
    m = _DATE.match(value)
    ok = bool(m)
    if m:
        year, month, day = m.group(2), m.group(3), m.group(4)
        try:
            datetime(int(year), int(month or 1), int(day or 1))
        except ValueError:
            ok = False
    if not ok:
        problems.append(f"Unknown date: {value}")
        return "0"
    text = m.group(2) + (f"-{month}" if month else "") + (f"-{day}" if day else "")
    params.append(text)
    return f"substr({column}, 1, {len(text)}) {m.group(1) or '='} ?"


def like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _compile(node, now, params, problems):
    kind = node[0]
    if kind == "text":
        params += [like(node[1])] * 3
        return "(slug LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\' OR created_by LIKE ? ESCAPE '\\')"
    if kind == "kv":
        _, key, values = node
        if key == "status":
            parts = []
            for v in values:
                sql, needs_now = _STATUS_SQL.get(v.lower(), (None, False))
                if sql is None:
                    problems.append(f"Unknown status: {v}")
                    parts.append("0")
                else:
                    parts.append(sql)
                    if needs_now:
                        params.append(now)
            return "(" + " OR ".join(parts) + ")"
        if key in DATE_COLUMNS:
            return "(" + " OR ".join(_date_condition(key, v, params, problems) for v in values) + ")"
        if key == "creator":
            params += [v.lower() for v in values]
            return "(lower(created_by) IN (" + ",".join("?" * len(values)) + "))"
        column = key                                        # slug or target
        params += [like(v) for v in values]
        return "(" + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for _ in values) + ")"
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
    """What follows `sort_by=` for a sort, or "" for the default (newest first)."""
    if key == "created" and not reverse:
        return ""
    return f"{'-' if reverse else ''}{key}"


def sort_term(key: str, reverse: bool) -> str:
    """The whole sort_by term for a sort, or "" for the default."""
    value = sort_value(key, reverse)
    return f"sort_by={value}" if value else ""


def _remove(text: str, toks: list[Tok]) -> str:
    for t in sorted(toks, key=lambda t: t.start, reverse=True):
        end = t.end
        while end < len(text) and text[end].isspace():
            end += 1
        start = t.start
        if end == len(text):                                # at the end: take the whitespace before it instead
            while start > 0 and text[start - 1].isspace():
                start -= 1
        text = text[:start] + text[end:]
    return text.strip()


def has_top_level_or(toks: list[Tok]) -> bool:
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
    toks = [t for t in tokenize(text) if t.kind == "term" and t.key == "sortby"]
    base = _remove(text, toks)
    term = sort_term(key, reverse)
    return f"{base} {term}".strip() if term else base


def quote_value(value: str) -> str:
    return '"' + value.replace('"', "") + '"' if (not value or re.search(r'[\s()"]', value)) else value
