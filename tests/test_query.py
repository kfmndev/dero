"""The search language: tokenizer, parser and the SQL it produces."""

import sqlite3
from datetime import date

import pytest

from dero import query

NOW = "2026-06-15T12:00:00Z"


def make_db():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE links (id INTEGER PRIMARY KEY, slug TEXT, target TEXT, enabled INTEGER, visits INTEGER,
                            created_by TEXT, created_at TEXT, expires_at TEXT);
    """)
    rows = [  # slug, target, enabled, visits, creator, expires
        ("aaa", "https://github.com/dero", 1, 10, "julian", None),
        ("bbb", "https://example.com/blog", 1, 5, "julian", "2020-01-01T23:59:59Z"),  # expired
        ("ccc", "https://example.com/shop", 0, 7, "anna", None),  # disabled
        ("ddd", "https://github.com/other", 1, 1, "anna", "2099-01-01T23:59:59Z"),  # active, expires later
        ("eee", "https://news.example.org/", 0, 3, "Anna Maria", "2020-02-02T23:59:59Z"),  # disabled AND expired
    ]
    for i, (slug, target, enabled, visits, who, exp) in enumerate(rows, 1):
        db.execute(
            "INSERT INTO links VALUES (?,?,?,?,?,?,?,?)",
            (i, slug, target, enabled, visits, who, "2026-01-01T00:00:00Z", exp),
        )
    return db


DB = make_db()


def find(text):
    """-> (slugs, parsed)"""
    parsed = query.parse(text, NOW)
    sql = "SELECT slug FROM links" + (f" WHERE {parsed.where}" if parsed.where else "") + " ORDER BY id"
    return [r[0] for r in DB.execute(sql, parsed.params)], parsed


def slugs(text):
    return find(text)[0]


# ------------------------------------------------------------------ what matches
def test_empty_query_matches_everything():
    assert slugs("") == slugs("   ") == ["aaa", "bbb", "ccc", "ddd", "eee"]


def test_free_text_searches_slug_target_and_creator():
    assert slugs("github") == ["aaa", "ddd"]  # target
    assert slugs("bbb") == ["bbb"]  # slug
    assert slugs("julian") == ["aaa", "bbb"]  # creator
    assert slugs("JULIAN") == ["aaa", "bbb"]  # case-insensitive
    assert slugs("github other") == ["ddd"]  # two terms = both
    assert slugs('"Anna Maria"') == ["eee"]  # a phrase


def test_keys_chain_together():
    assert slugs("status=expired") == ["bbb", "eee"]
    assert slugs("status=expired creator=julian") == ["bbb"]
    assert slugs("status=expired creator=julian sortby=visits") == ["bbb"]
    assert slugs("creator=anna") == ["ccc", "ddd"]  # exact, not a part of "Anna Maria"
    assert slugs('creator="anna maria"') == ["eee"]
    assert slugs("slug=a target=github") == ["aaa"]  # a part of the slug, and a part of the target
    assert slugs("slug=d target=github") == ["ddd"]


def test_comma_means_or_within_a_key():
    assert slugs("status=active,disabled") == ["aaa", "ccc", "ddd", "eee"]
    assert slugs("creator=julian,anna") == ["aaa", "bbb", "ccc", "ddd"]
    assert slugs("target=blog,shop") == ["bbb", "ccc"]


def test_status_meanings():
    assert slugs("status=active") == ["aaa", "ddd"]  # enabled and not expired
    assert slugs("status=disabled") == ["ccc", "eee"]
    assert slugs("status=expired") == ["bbb", "eee"]  # eee is both disabled and expired
    assert slugs("STATUS=Expired") == ["bbb", "eee"]  # keys and values ignore case


def test_negation():
    assert slugs("!status=expired") == ["aaa", "ccc", "ddd"]
    assert slugs("status!=expired") == ["aaa", "ccc", "ddd"]
    assert slugs("!github") == ["bbb", "ccc", "eee"]
    assert slugs("!creator=julian !status=disabled") == ["ddd"]
    assert slugs("!(status=expired or status=disabled)") == ["aaa", "ddd"]
    assert slugs("! github") == ["bbb", "ccc", "eee"]  # a space after ! is fine
    assert slugs("!!github") == ["aaa", "ddd"]  # double negation


def test_and_or_and_parentheses():
    assert slugs("creator=julian or creator=anna") == ["aaa", "bbb", "ccc", "ddd"]
    assert slugs("creator=julian || status=disabled") == ["aaa", "bbb", "ccc", "eee"]
    assert slugs("status=expired and creator=julian") == ["bbb"]
    assert slugs("status=expired && creator=julian") == ["bbb"]
    assert slugs("CREATOR=julian OR creator=anna") == ["aaa", "bbb", "ccc", "ddd"]
    # "and" binds tighter than "or"
    assert slugs("creator=julian or creator=anna status=disabled") == ["aaa", "bbb", "ccc"]
    assert slugs("(creator=julian or creator=anna) status=disabled") == ["ccc"]
    assert slugs("((creator=julian)) (status=expired)") == ["bbb"]


def test_words_and_or_can_be_searched_when_quoted_and_unknown_keys_are_text():
    assert slugs('"or"') == ["eee"]  # quoted, "or" is text (found in example.org)
    assert (
        slugs("or") == slugs("and") == ["aaa", "bbb", "ccc", "ddd", "eee"]
    )  # unquoted it is an operator with nothing to join
    assert slugs("or_") == []  # "_" is a literal character, not a wildcard
    assert slugs('"example"') == ["bbb", "ccc", "eee"]
    assert slugs("blog=1") == []  # unknown key -> searched as the text "blog=1"
    assert slugs("https://github.com") == ["aaa", "ddd"]  # a pasted URL is plain text
    assert slugs("target=https://github.com/dero") == ["aaa"]


# ------------------------------------------------------------------ sorting
def test_sortby_is_a_directive_not_a_filter():
    rows, parsed = find("sortby=visits")
    assert rows == ["aaa", "bbb", "ccc", "ddd", "eee"] and parsed.sort == ("visits", False) and parsed.where is None
    assert find("sortby=-visits")[1].sort == ("visits", True)  # a minus reverses the usual order
    assert find("sort=slug")[1].sort == ("slug", False) and find("order=creator")[1].sort == ("creator", False)
    assert find("sortby=visits sortby=-slug")[1].sort == ("slug", True)  # the last one wins
    assert find("!sortby=visits")[1].sort == ("visits", False)  # negating a directive does nothing
    rows, parsed = find("creator=julian or sortby=visits")
    assert rows == ["aaa", "bbb"] and parsed.sort == ("visits", False)  # not an "or" branch that matches everything
    assert find("sortby=+visits")[1].sort == ("visits", False)


# ------------------------------------------------------------------ mistakes are handled, not raised
def test_problems_are_reported_but_never_fail():
    rows, parsed = find("status=nonsense")
    assert rows == [] and parsed.problems == ["Unknown status: nonsense"]
    assert find("status=expired,nonsense")[0] == ["bbb", "eee"]  # the valid part still works
    assert find("sortby=colour")[1].problems == ["Unknown sort: colour"]
    assert find("(status=expired")[1].problems == ["Missing )"] and find("(status=expired")[0] == ["bbb", "eee"]
    assert find("status=expired)")[1].problems == ["Unbalanced )"]
    for text in (
        "and",
        "or",
        "!",
        "&&",
        "||",
        "()",
        "( )",
        "!()",
        "status=",
        "creator=,,",
        "a and or b",
        '"',
        'creator="',
        "(((",
    ):
        find(text)  # must not raise


def test_values_are_bound_never_interpolated():
    nasty = "x'; DROP TABLE links; --"
    assert slugs(f'"{nasty}"') == [] and slugs(f'creator="{nasty}"') == [] and slugs(f'slug="{nasty}"') == []
    assert DB.execute("SELECT COUNT(*) FROM links").fetchone()[0] == 5
    assert slugs("%") == [] and slugs("_") == []  # LIKE wildcards are literal characters


# ------------------------------------------------------------------ editing queries as text
def test_sort_term_and_with_sort():
    assert query.sort_term("created", False) == "" and query.sort_term("created", True) == "sort_by=-created"
    assert query.sort_term("visits", False) == "sort_by=visits" and query.sort_term("slug", True) == "sort_by=-slug"
    assert query.with_sort("status=expired", "visits", False) == "status=expired sort_by=visits"
    assert query.with_sort("status=expired sortby=visits", "slug", True) == "status=expired sort_by=-slug"
    assert (
        query.with_sort("sortby=visits status=expired creator=julian", "created", False)
        == "status=expired creator=julian"
    )
    assert query.with_sort("", "visits", True) == "sort_by=-visits"


def test_add_term_wraps_when_there_is_a_top_level_or():
    assert query.add_term("", "status=expired") == "status=expired"
    assert query.add_term("foo", "status=expired") == "foo status=expired"
    assert query.add_term("a or b", "status=expired") == "(a or b) status=expired"
    assert query.add_term("(a or b) c", "status=expired") == "(a or b) c status=expired"
    assert slugs(query.add_term("creator=julian or creator=anna", "status=expired")) == ["bbb"]


@pytest.mark.parametrize(
    "value, quoted", [("julian", "julian"), ("Anna Maria", '"Anna Maria"'), ("a(b)", '"a(b)"'), ("", '""')]
)
def test_quote_value(value, quoted):
    assert query.quote_value(value) == quoted


def test_tokenizer_positions_cover_the_text():
    text = 'status=expired,disabled  !creator="Anna Maria" (a or b) && c'
    toks = query.tokenize(text)
    assert "".join(text[t.start : t.end] for t in toks) == text  # every character belongs to exactly one token
    kinds = [t.kind for t in toks if t.kind != "ws"]
    assert kinds == ["term", "not", "term", "lpar", "term", "or", "term", "rpar", "and", "term"]
    first, creator = toks[0], [t for t in toks if t.key == "creator"][0]
    assert first.key == "status" and first.values == ("expired", "disabled")
    assert creator.values == ("Anna Maria",)


def test_snake_case_names_match_the_dropdowns():
    assert slugs("created_by=julian") == slugs("creator=julian") == slugs("owner=julian") == slugs("by=julian")
    assert find("sort_by=-visits")[1].sort == ("visits", True) and find("sort_by=visits")[1].where is None


def test_date_filters():
    assert (
        slugs("created=2026")
        == slugs("created=2026-01")
        == slugs("created=2026-01-01")
        == ["aaa", "bbb", "ccc", "ddd", "eee"]
    )
    assert (
        slugs("created=2025") == [] and slugs("created>2026-01-01") == [] and slugs("created>=2026-01-01") == slugs("")
    )
    assert slugs("created<2026-02") == slugs("") and slugs("created<2026-01") == []
    assert (
        slugs("expires=2020") == ["bbb", "eee"]
        and slugs("expires=2020-01") == ["bbb"]
        and slugs("expires=2020-02-02") == ["eee"]
    )
    assert (
        slugs("expires<2021") == ["bbb", "eee"]
        and slugs("expires>2030") == ["ddd"]
        and slugs("expires<=2020-01-01") == ["bbb"]
        and slugs("expires>=2099") == ["ddd"]
    )
    assert slugs("expires=none") == slugs("expires=never") == ["aaa", "ccc"]
    assert slugs("expires!=none") == ["bbb", "ddd", "eee"] and slugs("!expires=none") == ["bbb", "ddd", "eee"]
    assert slugs("expires=2020-01,2099") == ["bbb", "ddd"]  # a comma is "or"
    assert slugs("expires>2020 expires<2099") == slugs("expires>2020 and expires<2099")
    assert slugs("expires=2020 creator=julian") == ["bbb"] and slugs("created=2026 or expires=2099") == slugs("")


def test_a_bare_optional_key_means_it_is_set():
    assert slugs("expires") == slugs("expires!=never") == ["bbb", "ddd", "eee"]
    assert slugs("!expires") == slugs("expires=never") == slugs("expires=none") == ["aaa", "ccc"]
    assert slugs("EXPIRES creator=julian") == slugs("expires creator=julian")
    assert slugs('"expires"') == []  # quoted, it is plain text again
    assert slugs("expires or slug=aaa") == ["aaa", "bbb", "ddd", "eee"]
    assert find("expires")[1].problems == []
    tok = [t for t in query.tokenize("expires") if t.kind == "term"][0]
    assert tok.key == "expires" and tok.op == "set" and tok.values == ()


def test_a_link_without_expiry_is_not_excluded_by_a_negated_date():
    assert slugs("!expires<2021") == ["aaa", "ccc", "ddd"] and slugs("expires!=2020") == ["aaa", "ccc", "ddd"]
    assert slugs("!expires>2030") == ["aaa", "bbb", "ccc", "eee"]


def test_comparisons_are_written_without_the_equals_sign():
    kinds = {text: query.tokenize(text)[0] for text in ("expires<=2027", "created>2026", "expires=<2027", "slug<abc")}
    assert (kinds["expires<=2027"].key, kinds["expires<=2027"].op, kinds["expires<=2027"].values) == (
        "expires",
        "<=",
        ("2027",),
    )
    assert kinds["created>2026"].key == "created" and kinds["created>2026"].op == ">"
    assert kinds["slug<abc"].key == "slug" and kinds["slug<abc"].op == "<"  # a known key: flagged when it filters
    # an operator after the equals sign is not a date
    for text in ("expires=<2027", "expires=>=2027", "created=>2026", "expires=<=2027-01-01"):
        rows, parsed = find(text)
        assert rows == [] and parsed.problems and parsed.problems[0].startswith("Unknown date"), text


def test_bad_dates_match_nothing_and_are_reported():
    for text in (
        "created=nonsense",
        "created=2026-13",
        "created=2026-02-30",
        "expires=<",
        "created=26",
        "expires<none",
    ):
        rows, parsed = find(text)
        assert rows == [] and parsed.problems and parsed.problems[0].startswith("Unknown date"), text
    assert find("created=2026-02-28")[1].problems == [] and find("created=2024-02-29")[1].problems == []
    assert find("created=none")[1].problems  # none is only for expires


# ------------------------------------------------------------------ wildcards and exact matches
def test_a_star_is_any_text_and_the_whole_value_must_match():
    assert slugs("slug=a*") == ["aaa"] and slugs("slug=*c") == ["ccc"] and slugs("slug=a*a") == ["aaa"]
    assert slugs("slug=*") == slugs("")
    assert slugs("target=https://github.com/*") == ["aaa", "ddd"]
    assert slugs("target=*.org/") == ["eee"]
    assert slugs("target=*example*") == ["bbb", "ccc", "eee"]
    assert slugs("target=example") == ["bbb", "ccc", "eee"]  # without a star it is still "contains"
    assert slugs("SLUG=A*") == ["aaa"]  # upper and lower case do not matter
    assert slugs("slug!=a*") == ["bbb", "ccc", "ddd", "eee"] and slugs("!slug=a*") == slugs("slug!=a*")
    assert slugs("slug=aaa,c*") == ["aaa", "ccc"]  # each alternative has its own rules
    assert slugs("slug=a_a") == [] and slugs("slug=a%") == []  # LIKE's own characters stay literal


def test_the_creator_is_exact_unless_there_is_a_star():
    assert slugs("created_by=anna") == ["ccc", "ddd"]  # not "Anna Maria"
    assert slugs("created_by=ann*") == ["ccc", "ddd", "eee"] and slugs("created_by=*maria") == ["eee"]
    assert slugs("created_by==anna") == slugs("created_by=anna")


def test_double_equals_is_an_exact_match_without_wildcards():
    assert slugs("slug==aaa") == ["aaa"] and slugs("slug==aa") == [] and slugs("slug=aa") == ["aaa"]
    assert slugs("target==https://github.com/dero") == ["aaa"] and slugs("TARGET==HTTPS://GITHUB.COM/DERO") == ["aaa"]
    assert slugs("target==https://github.com/*") == []  # a star is just a star here
    tok = [t for t in query.tokenize("slug==abc") if t.kind == "term"][0]
    assert (tok.key, tok.op, tok.negated, tok.values) == ("slug", "==", False, ("abc",))
    tok = [t for t in query.tokenize("slug!=abc") if t.kind == "term"][0]
    assert (tok.op, tok.negated) == ("=", True)


def test_an_operator_a_key_does_not_have_is_reported_and_matches_nothing():
    for text, key, op in (
        ("slug>abc", "slug", ">"),
        ("target<=x", "target", "<="),
        ("status>active", "status", ">"),
        ("created_by>=a", "creator", ">="),
        ("!slug<abc", "slug", "<"),
    ):
        rows, parsed = find(text)
        assert parsed.problems == [f"{key} does not support {op}"], text
        assert rows == (slugs("") if text.startswith("!") else []), text
    rows, parsed = find("sort_by>visits status=active")
    assert parsed.problems == ["sort_by does not support >"] and parsed.sort is None and rows == slugs("status=active")
    assert find("slug=abc visits>1")[1].problems == []  # what exists is fine


# ------------------------------------------------------------------ visits
def test_visits_filter():
    assert slugs("visits=10") == slugs("visits==10") == ["aaa"]
    assert slugs("visits!=10") == ["bbb", "ccc", "ddd", "eee"]
    assert slugs("visits>5") == ["aaa", "ccc"] and slugs("visits>=5") == ["aaa", "bbb", "ccc"]
    assert slugs("visits<3") == ["ddd"] and slugs("visits<=3") == ["ddd", "eee"]
    assert slugs("visits=5,7") == ["bbb", "ccc"] and slugs("visits>2 visits<8") == ["bbb", "ccc", "eee"]
    assert slugs("visits=") == slugs("")  # nothing typed yet: no filter
    assert slugs("visits") == []  # the bare word is free text again (no slug, target or creator holds it)


@pytest.mark.parametrize("text", ["visits=abc", "visits>-1", "visits=1.5", "visits=1000000000000000"])
def test_bad_visit_numbers_match_nothing_and_are_reported(text):
    rows, parsed = find(text)
    assert rows == [] and parsed.problems == [f"Unknown number: {text.split('=')[-1].split('>')[-1]}"]


# ------------------------------------------------------------------ relative dates
def test_relative_days():
    day = date(2026, 6, 15)
    rel = lambda value, today=day: query._relative_day(value, today)  # noqa: E731
    assert rel("today") == "2026-06-15" and rel("Yesterday") == "2026-06-14" and rel("tomorrow") == "2026-06-16"
    assert rel("-7d") == "2026-06-08" and rel("7d") == rel("+7d") == "2026-06-22" and rel("0d") == "2026-06-15"
    assert rel("2w") == "2026-06-29" and rel("-1w") == "2026-06-08" and rel("-3M") == "2026-03-15"
    assert rel("1y") == "2027-06-15" and rel("-1y") == "2025-06-15"
    assert rel("1m", date(2026, 1, 31)) == "2026-02-28" and rel("-1m", date(2024, 3, 31)) == "2024-02-29"  # month ends
    assert rel("-1y", date(2024, 2, 29)) == "2023-02-28"
    assert rel("12m", date(2026, 12, 31)) == "2027-12-31"
    for junk in ("", "d", "7", "7days", "-", "--7d", "12345d", "9999y", "-9999y", "2026"):
        assert rel(junk) is None, junk


def test_relative_dates_in_filters():
    # NOW is 2026-06-15, every link was created on 2026-01-01 (165 days earlier), bbb and eee are expired, ddd is not
    assert slugs("created<today") == slugs("") and slugs("created>today") == [] and slugs("created=today") == []
    assert slugs("created=-165d") == slugs("") and slugs("created>=-165d") == slugs("") and slugs("created>-165d") == []
    assert slugs("created>-6m") == slugs("") and slugs("created>-5m") == []
    assert slugs("expires<today") == slugs("status=expired") == ["bbb", "eee"]
    assert slugs("expires>tomorrow") == ["ddd"] and slugs("expires>0d expires<30d") == []
    assert slugs("expires<1000y") == ["bbb", "ddd", "eee"]  # a link that never expires is not "before" anything
    assert slugs("!expires<today") == ["aaa", "ccc", "ddd"]
    rows, parsed = find("created>=-5x")
    assert rows == [] and parsed.problems == ["Unknown date: -5x"]
    assert find("expires<9999y")[1].problems == ["Unknown date: 9999y"]  # too far for a date


# ------------------------------------------------------------------ sort_by=created_by
def test_the_creator_sort_has_both_names():
    assert find("sort_by=created_by")[1].sort == ("creator", False) == find("sort_by=creator")[1].sort
    assert find("sort_by=-created_by")[1].sort == ("creator", True)
    assert find("sort_by=CREATED_BY")[1].problems == []
