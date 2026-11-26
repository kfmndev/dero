"""The search language: tokenizer, parser and the SQL it produces."""
import sqlite3

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
        ("bbb", "https://example.com/blog", 1, 5, "julian", "2020-01-01T23:59:59Z"),        # expired
        ("ccc", "https://example.com/shop", 0, 7, "anna", None),                            # disabled
        ("ddd", "https://github.com/other", 1, 1, "anna", "2099-01-01T23:59:59Z"),          # active, expires later
        ("eee", "https://news.example.org/", 0, 3, "Anna Maria", "2020-02-02T23:59:59Z"),   # disabled AND expired
    ]
    for i, (slug, target, enabled, visits, who, exp) in enumerate(rows, 1):
        db.execute("INSERT INTO links VALUES (?,?,?,?,?,?,?,?)", (i, slug, target, enabled, visits, who, "2026-01-01T00:00:00Z", exp))
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
    assert slugs("github") == ["aaa", "ddd"]                  # target
    assert slugs("bbb") == ["bbb"]                            # slug
    assert slugs("julian") == ["aaa", "bbb"]                  # creator
    assert slugs("JULIAN") == ["aaa", "bbb"]                  # case-insensitive
    assert slugs("github other") == ["ddd"]                   # two terms = both
    assert slugs('"Anna Maria"') == ["eee"]                   # a phrase


def test_keys_chain_together():
    assert slugs("status=expired") == ["bbb", "eee"]
    assert slugs("status=expired creator=julian") == ["bbb"]
    assert slugs("status=expired creator=julian sortby=visits") == ["bbb"]
    assert slugs("creator=anna") == ["ccc", "ddd"]            # exact, not a part of "Anna Maria"
    assert slugs('creator="anna maria"') == ["eee"]
    assert slugs("slug=a target=github") == ["aaa"]           # a part of the slug, and a part of the target
    assert slugs("slug=d target=github") == ["ddd"]


def test_comma_means_or_within_a_key():
    assert slugs("status=active,disabled") == ["aaa", "ccc", "ddd", "eee"]
    assert slugs("creator=julian,anna") == ["aaa", "bbb", "ccc", "ddd"]
    assert slugs("target=blog,shop") == ["bbb", "ccc"]


def test_status_meanings():
    assert slugs("status=active") == ["aaa", "ddd"]                       # enabled and not expired
    assert slugs("status=disabled") == ["ccc", "eee"]
    assert slugs("status=expired") == ["bbb", "eee"]                      # eee is both disabled and expired
    assert slugs("STATUS=Expired") == ["bbb", "eee"]                      # keys and values ignore case


def test_negation():
    assert slugs("!status=expired") == ["aaa", "ccc", "ddd"]
    assert slugs("status!=expired") == ["aaa", "ccc", "ddd"]
    assert slugs("!github") == ["bbb", "ccc", "eee"]
    assert slugs("!creator=julian !status=disabled") == ["ddd"]
    assert slugs("!(status=expired or status=disabled)") == ["aaa", "ddd"]
    assert slugs("! github") == ["bbb", "ccc", "eee"]                     # a space after ! is fine
    assert slugs("!!github") == ["aaa", "ddd"]                            # double negation


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
    assert slugs('"or"') == ["eee"]                                         # quoted, "or" is text (found in example.org)
    assert slugs("or") == slugs("and") == ["aaa", "bbb", "ccc", "ddd", "eee"]   # unquoted it is an operator with nothing to join
    assert slugs("or_") == []                                               # "_" is a literal character, not a wildcard
    assert slugs('"example"') == ["bbb", "ccc", "eee"]
    assert slugs("blog=1") == []                                            # unknown key -> searched as the text "blog=1"
    assert slugs("https://github.com") == ["aaa", "ddd"]                    # a pasted URL is plain text
    assert slugs("target=https://github.com/dero") == ["aaa"]


# ------------------------------------------------------------------ sorting
def test_sortby_is_a_directive_not_a_filter():
    rows, parsed = find("sortby=visits")
    assert rows == ["aaa", "bbb", "ccc", "ddd", "eee"] and parsed.sort == ("visits", False) and parsed.where is None
    assert find("sortby=-visits")[1].sort == ("visits", True)                # a minus reverses the usual order
    assert find("sort=slug")[1].sort == ("slug", False) and find("order=creator")[1].sort == ("creator", False)
    assert find("sortby=visits sortby=-slug")[1].sort == ("slug", True)       # the last one wins
    assert find("!sortby=visits")[1].sort == ("visits", False)                # negating a directive does nothing
    rows, parsed = find("creator=julian or sortby=visits")
    assert rows == ["aaa", "bbb"] and parsed.sort == ("visits", False)         # not an "or" branch that matches everything
    assert find("sortby=+visits")[1].sort == ("visits", False)


# ------------------------------------------------------------------ mistakes are handled, not raised
def test_problems_are_reported_but_never_fail():
    rows, parsed = find("status=nonsense")
    assert rows == [] and parsed.problems == ["Unknown status: nonsense"]
    assert find("status=expired,nonsense")[0] == ["bbb", "eee"]              # the valid part still works
    assert find("sortby=colour")[1].problems == ["Unknown sort: colour"]
    assert find("(status=expired")[1].problems == ["Missing )"] and find("(status=expired")[0] == ["bbb", "eee"]
    assert find("status=expired)")[1].problems == ["Unbalanced )"]
    for text in ("and", "or", "!", "&&", "||", "()", "( )", "!()", "status=", "creator=,,", "a and or b", '"', 'creator="', "((("):
        find(text)                                                            # must not raise


def test_values_are_bound_never_interpolated():
    nasty = "x'; DROP TABLE links; --"
    assert slugs(f'"{nasty}"') == [] and slugs(f'creator="{nasty}"') == [] and slugs(f'slug="{nasty}"') == []
    assert DB.execute("SELECT COUNT(*) FROM links").fetchone()[0] == 5
    assert slugs("%") == [] and slugs("_") == []                              # LIKE wildcards are literal characters


# ------------------------------------------------------------------ editing queries as text
def test_sort_term_and_with_sort():
    assert query.sort_term("created", False) == "" and query.sort_term("created", True) == "sortby=-created"
    assert query.sort_term("visits", False) == "sortby=visits" and query.sort_term("slug", True) == "sortby=-slug"
    assert query.with_sort("status=expired", "visits", False) == "status=expired sortby=visits"
    assert query.with_sort("status=expired sortby=visits", "slug", True) == "status=expired sortby=-slug"
    assert query.with_sort("sortby=visits status=expired creator=julian", "created", False) == "status=expired creator=julian"
    assert query.with_sort("", "visits", True) == "sortby=-visits"


def test_add_term_wraps_when_there_is_a_top_level_or():
    assert query.add_term("", "status=expired") == "status=expired"
    assert query.add_term("foo", "status=expired") == "foo status=expired"
    assert query.add_term("a or b", "status=expired") == "(a or b) status=expired"
    assert query.add_term("(a or b) c", "status=expired") == "(a or b) c status=expired"
    assert slugs(query.add_term("creator=julian or creator=anna", "status=expired")) == ["bbb"]


@pytest.mark.parametrize("value, quoted", [("julian", "julian"), ("Anna Maria", '"Anna Maria"'), ("a(b)", '"a(b)"'), ("", '""')])
def test_quote_value(value, quoted):
    assert query.quote_value(value) == quoted


def test_tokenizer_positions_cover_the_text():
    text = 'status=expired,disabled  !creator="Anna Maria" (a or b) && c'
    toks = query.tokenize(text)
    assert "".join(text[t.start:t.end] for t in toks) == text                  # every character belongs to exactly one token
    kinds = [t.kind for t in toks if t.kind != "ws"]
    assert kinds == ["term", "not", "term", "lpar", "term", "or", "term", "rpar", "and", "term"]
    first, creator = toks[0], [t for t in toks if t.key == "creator"][0]
    assert first.key == "status" and first.values == ("expired", "disabled")
    assert creator.values == ("Anna Maria",)
