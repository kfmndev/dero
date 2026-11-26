import base64
import html as html_lib
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from dero import create_app
from dero.db import get_db
from dero.display import highlight_slug, target_box
from dero.forms import ALPHABETS, random_slug
from dero.passwd import main as passwd_main
from dero.passwd import make_line

USER = {"Remote-User": "alice", "Remote-Groups": "dero-users"}
USER2 = {"Remote-User": "bob", "Remote-Groups": "dero-users"}
ADMIN = {"Remote-User": "root", "Remote-Groups": "dero-admins,other"}


def js_source(client):
    """All the page's own scripts as one text: they are plain scripts listed in the base template."""
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    paths = re.findall(r'<script src="(/static/js/[^"]+)"', html)
    assert paths, "no scripts found in the page"
    return "\n".join(client.get(path).get_data(as_text=True) for path in paths)


def flat_css(css):
    """The stylesheet on one line per rule, whatever its formatting, for assertions about exact declarations."""
    return re.sub(r"\s+", " ", css)


def css_rule(css, selector):
    """The declarations the rules with exactly this selector give together, as {property: value} (later rules win)."""
    flat = re.sub(r"\s+", " ", css)
    found = {}

    for m in re.finditer(r"(?:^|[}/]) ?" + re.escape(selector) + r" ?\{([^{}]*)\}", flat):
        pairs = (d.split(":", 1) for d in m.group(1).split(";") if ":" in d)
        found.update({name.strip(): value.strip().replace(" / ", "/") for name, value in pairs})
    assert found, f"no rule for {selector}"

    return found


def flat_js(js):
    """The scripts with line breaks and indentation collapsed, for assertions about exact statements."""
    return re.sub(r"\s+", " ", js)


def flat(html):
    """Page markup with the template's line breaks and indentation removed, for assertions about exact tags."""
    return re.sub(r">\s+<", "><", re.sub(r"\s+", " ", html))


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "t.db"), "SECRET_KEY": "test", "TESTING": True, "AUTH_MODE": "proxy"})


@pytest.fixture
def client(app):
    return app.test_client()


def token(client, headers):
    html = client.get("/admin/", headers=headers).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def post(client, path, headers, **data):
    return client.post(path, headers=headers, data={"csrf": token(client, headers), **data})


def visits(client, headers):
    html = client.get("/admin/", headers=headers).get_data(as_text=True)
    return html


def test_access_control(client):
    assert client.get("/admin/").status_code == 403
    assert client.get("/admin/", headers={"Remote-User": "eve"}).status_code == 403
    assert client.get("/admin/", headers={"Remote-User": "eve", "Remote-Groups": "nope"}).status_code == 403
    assert client.get("/admin/", headers=USER).status_code == 200


def test_proxy_secret(app):
    app.config["PROXY_SECRET"] = "s3"
    c = app.test_client()
    assert c.get("/admin/", headers=USER).status_code == 403
    assert c.get("/admin/", headers={**USER, "X-Proxy-Secret": "s3"}).status_code == 200


def test_csrf_required(client):
    r = client.post("/admin/links", headers=USER, data={"target": "https://example.com"})
    assert r.status_code == 400


def test_create_and_redirect_counts_visits(client, app):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="abc")
    r = client.get("/abc")
    assert r.status_code == 302 and r.headers["Location"] == "https://example.com/a"
    assert r.headers["Cache-Control"] == "no-store"
    client.get("/abc")
    client.get("/abc/")
    with app.app_context():
        row = get_db().execute("SELECT visits, created_by FROM links WHERE slug='abc'").fetchone()
        assert (row["visits"], row["created_by"]) == (3, "alice")


def test_random_slug_and_duplicate(client):
    post(client, "/admin/links", USER, target="https://example.com")
    post(client, "/admin/links", USER, target="https://example.com/x", slug="dup")
    r = post(client, "/admin/links", USER, target="https://example.com/y", slug="dup")
    assert client.get("/dup").headers["Location"] == "https://example.com/x"
    assert r.status_code == 400 and "already taken" in r.get_data(as_text=True)


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://x.y/z", "notaurl", "https://"])
def test_rejects_bad_urls(client, bad):
    post(client, "/admin/links", USER, target=bad, slug="bad")
    assert client.get("/bad").status_code == 404


def expire(app, slug):
    """Make an existing link expired (the form refuses to create one that already is)."""

    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE links SET expires_at = '2000-01-01T23:59:59Z' WHERE slug = ?", (slug,))
        conn.commit()


def test_disable_and_expiry(client, app):
    post(client, "/admin/links", USER, target="https://example.com", slug="gone")
    assert client.get("/gone").status_code == 302
    expire(app, "gone")
    assert client.get("/gone").status_code == 404
    post(client, "/admin/links", USER, target="https://example.com", slug="off")
    assert client.get("/off").status_code == 302
    post(client, "/admin/links/2/toggle", USER)
    assert client.get("/off").status_code == 404


def test_ownership(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="mine")
    assert post(client, "/admin/links/1/delete", USER2).status_code == 404
    assert client.get("/mine").status_code == 302
    assert post(client, "/admin/links/1/delete", ADMIN).status_code == 302
    assert client.get("/mine").status_code == 404


def test_rules_admin_only(client):
    assert client.get("/admin/rules", headers=USER).status_code == 403
    assert post(client, "/admin/rules", USER, pattern="x", target="https://e.com").status_code == 403


def test_glob_rules_priority_and_fallback(client):
    post(client, "/admin/rules", ADMIN, pattern="gh/*", target="https://github.com/{1}", priority="50")
    post(client, "/admin/rules", ADMIN, pattern="gh/**", target="https://example.com/all/{1}", priority="10")
    assert client.get("/gh/foo").headers["Location"] == "https://example.com/all/foo"  # lower number wins
    post(client, "/admin/rules/1/priority", ADMIN, priority="1")
    assert client.get("/gh/foo").headers["Location"] == "https://github.com/foo"
    assert client.get("/gh/foo/bar").headers["Location"] == "https://example.com/all/foo/bar"
    assert client.get("/nothing").status_code == 404
    post(client, "/admin/settings/fallback", ADMIN, fallback_url="https://example.com/rick")
    assert client.get("/nothing").headers["Location"] == "https://example.com/rick"
    assert client.get("/").headers["Location"] == "https://example.com/rick"


def test_exact_link_beats_rule(client):
    post(client, "/admin/rules", ADMIN, pattern="**", target="https://example.com/{1}")
    post(client, "/admin/links", USER, target="https://real.example", slug="abc")
    assert client.get("/abc").headers["Location"] == "https://real.example"


def test_regex_rule_and_timeout(client):
    post(client, "/admin/rules", ADMIN, pattern=r"v(\d+)", match_type="regex", target="https://e.com/ver/{1}")
    assert client.get("/v42").headers["Location"] == "https://e.com/ver/42"
    post(
        client, "/admin/rules", ADMIN, pattern=r"(a+)+$", match_type="regex", target="https://e.com/evil", priority="1"
    )

    t = time.time()
    assert client.get("/" + "a" * 40 + "!").status_code == 404  # catastrophic pattern is cut off
    assert time.time() - t < 2


def test_rule_validation(client):
    post(client, "/admin/rules", ADMIN, pattern="a/*", target="https://e.com/{2}")  # placeholder > groups
    post(client, "/admin/rules", ADMIN, pattern="(", match_type="regex", target="https://e.com")
    post(client, "/admin/rules", ADMIN, pattern="b", target="javascript:alert(1)")
    assert client.get("/a/x").status_code == 404 and client.get("/b").status_code == 404


def test_target_placeholder_is_escaped(client):
    post(client, "/admin/rules", ADMIN, pattern="q/*", target="https://e.com/s?q={1}")
    assert client.get("/q/a b").headers["Location"] == "https://e.com/s?q=a%20b"


def test_admin_slug_reserved(client):
    r = post(client, "/admin/links", USER, target="https://example.com", slug="admin")
    assert r.status_code == 400 and '<code class="slug">admin</code> is reserved.' in r.get_data(as_text=True)
    assert client.get("/admin").status_code in (301, 308, 404)  # the UI, never a short link


def test_custom_admin_path(tmp_path):
    app = create_app(
        {"DATABASE": str(tmp_path / "c.db"), "SECRET_KEY": "t", "ADMIN_PATH": "manage", "AUTH_MODE": "proxy"}
    )
    c = app.test_client()
    assert c.get("/manage/", headers=USER).status_code == 200
    assert c.get("/admin/", headers=USER).status_code == 404


# ---------------------------------------------------------------- basic auth


def basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


@pytest.fixture
def bclient(tmp_path):
    users = tmp_path / "users.txt"
    users.write_text(
        "# comment\n"
        + make_line("alice", "user", "alice-password")
        + "\n"
        + make_line("root", "admin", "root-password")
        + "\n"
        + "garbage line\n"
    )
    app = create_app({"DATABASE": str(tmp_path / "b.db"), "SECRET_KEY": "t", "USERS_FILE": str(users)})
    return app.test_client()


def test_basic_requires_credentials(bclient):
    r = bclient.get("/admin/")
    assert r.status_code == 401 and "Basic" in r.headers["WWW-Authenticate"]
    assert bclient.get("/admin/", headers=basic("alice", "wrong-password")).status_code == 401
    assert bclient.get("/admin/", headers=basic("nobody", "alice-password")).status_code == 401
    assert bclient.get("/admin/", headers=basic("alice", "alice-password")).status_code == 200


def test_basic_roles_and_creator(bclient):
    a, r = basic("alice", "alice-password"), basic("root", "root-password")
    post(bclient, "/admin/links", a, target="https://example.com", slug="x")
    assert bclient.get("/x").status_code == 302  # short links stay public
    assert bclient.get("/admin/rules", headers=a).status_code == 403  # users can't manage rules
    assert bclient.get("/admin/rules", headers=r).status_code == 200
    assert "alice" in bclient.get("/admin/", headers=r).get_data(as_text=True)


def test_basic_csrf_still_enforced(bclient):
    h = basic("alice", "alice-password")
    assert bclient.post("/admin/links", headers=h, data={"target": "https://example.com"}).status_code == 400


def test_basic_no_users_file_denies_everyone(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "n.db"), "SECRET_KEY": "t", "USERS_FILE": str(tmp_path / "none")})
    assert app.test_client().get("/admin/", headers=basic("a", "b")).status_code == 401


def test_passwd_cli(tmp_path, monkeypatch):
    f = tmp_path / "u.txt"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("a-long-password\n"))
    assert passwd_main(["bob", "--role", "admin", "--password-stdin", "--file", str(f)]) == 0
    name, role, pwhash = f.read_text().strip().split(":", 2)
    assert (name, role) == ("bob", "admin") and pwhash.startswith("scrypt:")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("short\n"))
    assert passwd_main(["bob", "--password-stdin"]) == 1


def test_auth_none_everyone_is_admin(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "x.db"), "SECRET_KEY": "t", "AUTH_MODE": "none", "NONE_USER": "me"})
    c = app.test_client()
    assert c.get("/admin/").status_code == 200 and c.get("/admin/rules").status_code == 200
    post(c, "/admin/links", {}, target="https://example.com", slug="n")
    assert c.get("/n").status_code == 302
    assert "me" in c.get("/admin/").get_data(as_text=True)
    assert c.post("/admin/links", data={"target": "https://example.com"}).status_code == 400  # CSRF still on


def test_unknown_auth_mode_rejected(tmp_path):
    with pytest.raises(RuntimeError):
        create_app({"DATABASE": str(tmp_path / "y.db"), "SECRET_KEY": "t", "AUTH_MODE": "magic"})


def test_static_slug_reserved_and_assets_served(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="static")
    assert client.get("/static").status_code == 404
    assert client.get("/static/style.css").status_code == 200


# ---------------------------------------------------------------- sorting / filtering
def seed_links(client, app):
    post(client, "/admin/links", USER, target="https://example.com/apple", slug="aaa")
    post(client, "/admin/links", USER, target="https://example.com/banana", slug="bbb")
    post(client, "/admin/links", USER2, target="https://other.org/cherry", slug="ccc")
    post(client, "/admin/links", USER, target="https://example.com/old", slug="old")
    expire(app, "old")
    for _ in range(3):
        client.get("/bbb")
    client.get("/aaa")
    post(client, "/admin/links/1/toggle", USER)  # disable "aaa"


def slugs(client, headers, query=""):
    html = client.get("/admin/" + query, headers=headers).get_data(as_text=True)
    return re.findall(r'class="slug">([a-z0-9]+)</code>', html)


def test_sorting(client, app):
    seed_links(client, app)
    assert slugs(client, ADMIN, "?sort=slug&dir=asc") == ["aaa", "bbb", "ccc", "old"]
    assert slugs(client, ADMIN, "?sort=slug&dir=desc") == ["old", "ccc", "bbb", "aaa"]
    assert slugs(client, ADMIN, "?sort=visits&dir=desc")[0] == "bbb"
    assert slugs(client, ADMIN, "?sort=expires&dir=asc")[0] == "old"  # rows without expiry come last
    assert slugs(client, ADMIN, "?sort=bogus; DROP TABLE links&dir=sideways")  # invalid values fall back to the default
    assert slugs(client, ADMIN, "?order=slug:desc") == ["old", "ccc", "bbb", "aaa"]  # the dropdown
    assert slugs(client, ADMIN, "?order=nonsense")


def test_filtering(client, app):
    seed_links(client, app)
    assert slugs(client, ADMIN, "?q=cherry") == ["ccc"]
    assert slugs(client, ADMIN, "?q=BOB") == ["ccc"]  # creator, case-insensitive
    assert slugs(client, ADMIN, "?status=disabled") == ["aaa"]
    assert slugs(client, ADMIN, "?status=expired") == ["old"]
    assert sorted(slugs(client, ADMIN, "?status=active")) == ["bbb", "ccc"]
    assert slugs(client, ADMIN, "?owner=bob") == ["ccc"]
    assert slugs(client, ADMIN, "?q=%25") == []  # % is literal, not a wildcard
    assert "No links match." in client.get("/admin/?q=zzz", headers=ADMIN).get_data(as_text=True)


def test_filters_never_expose_other_users_links(client, app):
    seed_links(client, app)
    assert "ccc" not in slugs(client, USER)
    assert "ccc" not in slugs(client, USER, "?owner=bob&q=cherry")
    assert slugs(client, USER2, "?owner=alice") == ["ccc"]


def test_toggle_returns_to_same_view_only(client, app):
    seed_links(client, app)
    r = post(client, "/admin/links/2/toggle", USER, back="/admin/?status=active&sort=slug")
    assert r.headers["Location"] == "/admin/?status=active&sort=slug"
    for evil in ("https://evil.example/", "//evil.example/", "/other", "/admin\\evil"):
        assert post(client, "/admin/links/2/toggle", USER, back=evil).headers["Location"] == "/admin/"


# ---------------------------------------------------------------- form errors stay in the form
def test_failed_create_keeps_input_and_shows_error_in_the_card(client):
    post(client, "/admin/links", USER, target="https://example.com/x", slug="taken")
    r = post(
        client, "/admin/links", USER, target="https://example.com/mine?a=1&b=2", slug="taken", expires_at="2031-05-06"
    )
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    # what was typed is still in the fields
    assert 'value="https://example.com/mine?a=1&amp;b=2"' in html
    assert (
        'name="slug" type="text" placeholder="my-link" value="taken"' in html
        and '<option value="slug" selected>' in html
    )  # "Custom slug" restored
    assert 'value="2031-05-06"' in html
    # the message is inside the "New link" card (before the "links" card), next to the offending field
    card = html[html.index("New link") : html.index("Slugs are served from")]
    assert 'Slug <code class="slug">taken</code> is already taken.' in card and 'role="alert"' in card
    assert re.search(r'name="slug"[^>]*aria-invalid="true"', html) and 'name="target"' in html
    assert not re.search(r'name="target"[^>]*aria-invalid', html)
    # ... and not in the page-level flash area
    assert 'class="flash' not in html


def test_each_field_error_is_tagged_and_nothing_is_created(client):
    for data, field in [
        ({"target": "javascript:alert(1)"}, "target"),
        ({"target": "https://example.com", "slug": "bad slug!"}, "slug"),
        ({"target": "https://example.com", "slug": "static"}, "slug"),
        ({"target": "https://example.com", "expires_at": "31/12/2030"}, "expires_at"),
    ]:
        r = post(client, "/admin/links", USER, **data)
        html = r.get_data(as_text=True)
        assert r.status_code == 400
        assert re.search(rf'name="{field}"[^>]*aria-invalid="true"', html), data
        for key, value in data.items():  # input is preserved
            assert f'value="{value}"' in html, (data, key)
    assert "No links yet." in client.get("/admin/", headers=USER).get_data(as_text=True)


def test_success_message_is_shown_in_the_card_and_cleared_form(client):
    r = post(client, "/admin/links", USER, target="https://example.com", slug="fine")
    assert r.status_code == 302
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    card = html[html.index("New link") : html.index("Slugs are served from")]
    assert "Created" in card and 'class="form-ok"' in card and 'class="flash' not in html
    assert "form-ok" not in client.get("/admin/", headers=USER).get_data(as_text=True)  # shown once


def test_row_actions_after_failed_create_still_work(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="one")
    html = post(client, "/admin/links", USER, target="nope").get_data(as_text=True)
    assert 'name="back" value="/admin/"' in html  # not "/admin/links", which has no GET route


# ---------------------------------------------------------------- base URL, row layout
def test_base_url_is_used_for_display_and_copy(tmp_path):
    app = create_app(
        {
            "DATABASE": str(tmp_path / "u.db"),
            "SECRET_KEY": "t",
            "AUTH_MODE": "proxy",
            "BASE_URL": "https://s.example.com/",
        }
    )
    c = app.test_client()
    post(c, "/admin/links", USER, target="https://example.com", slug="abc")
    html = c.get("/admin/", headers=USER).get_data(as_text=True)
    assert 'data-copy="https://s.example.com/abc"' in html and 'href="https://s.example.com/abc"' in html
    assert (
        "<code>s.example.com</code>" in html
        and 'Created <span class="base">https://s.example.com/</span><code class="slug">abc</code>' in html
    )
    assert "localhost" not in html


@pytest.mark.parametrize(
    "bad", ["s.example.com", "ftp://s.example.com", "https://s.example.com/x", "https://s.example.com/?a=1"]
)
def test_invalid_base_url_is_rejected(tmp_path, bad):
    with pytest.raises(RuntimeError):
        create_app({"DATABASE": str(tmp_path / "u.db"), "SECRET_KEY": "t", "AUTH_MODE": "proxy", "BASE_URL": bad})


def test_base_url_defaults_to_request_host(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="abc")
    assert 'data-copy="http://localhost/abc"' in client.get("/admin/", headers=USER).get_data(as_text=True)


def test_row_layout_copy_beside_link_delete_in_details(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    row = html[html.index('<tr class="item') : html.index('<tr class="detail"')]
    detail = html[html.index('<tr class="detail"') : html.index("</tbody>")]
    assert row.count("data-copy") == 2 and 'class="actions"' not in row and "/delete" not in row
    # every link gets "open" first, then "copy"
    for what in ("slug", "target"):
        assert row.count(f'aria-label="Open {what}"') == 1 and row.count(f'aria-label="Copy {what}"') == 1
        assert row.index(f'aria-label="Open {what}"') < row.index(f'aria-label="Copy {what}"')
    assert "/delete" in detail and "</svg>Delete</button>" in detail
    assert 'id="links-results"' in html and 'id="filter-live"' in html


def test_an_already_expired_link_can_be_created(client):
    """The form warns about a past expiry date; the server lets it through."""

    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    r = post(client, "/admin/links", USER, target="https://example.com/x", slug="late", expires_at=yesterday)
    assert r.status_code == 302
    assert client.get("/late").status_code == 404  # expired, so it doesn't redirect
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    assert (
        re.search(
            r'<span class="expired-mark" data-expired="[^"]+" role="img" aria-label="Expired on \d{4}-\d\d-\d\d"', html
        )
        and 'class="badge"' not in html
    )
    assert not any(
        " min=" in tag for tag in re.findall(r'<input[^>]*type="date"[^>]*>', html)
    )  # past days are selectable


# ---------------------------------------------------------------- regressions: Clear button / swapped fragment
def test_swapped_fragment_contains_no_style(client):
    """The page JS swaps #links-results into the live page; a <noscript><style> in it would open every details row."""
    post(client, "/admin/links", USER, target="https://example.com", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    fragment = html[html.index('id="links-results"') : html.index("</section>", html.index('id="links-results"'))]
    assert "<style" not in fragment
    assert "tr.detail[hidden]" in html and html.index("<noscript><style>") < html.index('id="links-results"')


def test_reset_button_is_disabled_not_hidden(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="abc")
    plain = client.get("/admin/", headers=USER).get_data(as_text=True)
    filtered = client.get("/admin/?q=abc", headers=USER).get_data(as_text=True)
    for html, state in ((plain, "true"), (filtered, "false")):
        tag = re.search(r'<a class="btn" id="reset-filters"[^>]*>', html).group(0)
        assert f'aria-disabled="{state}"' in tag and " hidden" not in tag


def test_delete_uses_the_custom_dialog_not_window_confirm(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    post(client, "/admin/rules", ADMIN, pattern="gh/*", target="https://github.com/{1}")
    links = client.get("/admin/", headers=USER).get_data(as_text=True)
    rules = client.get("/admin/rules", headers=ADMIN).get_data(as_text=True)
    for html in (links, rules):
        assert "confirm(" not in html and "onsubmit" not in html
        assert '<dialog id="confirm"' in html and html.index('id="confirm-yes"') < html.index(
            'value="no"'
        )  # accept first (left)
    assert 'data-confirm-name="http://localhost/abc"' in links and 'data-confirm-name="gh/*"' in rules


# ---------------------------------------------------------------- open + copy icons everywhere, expiry editing
def test_every_link_has_open_then_copy(tmp_path):
    app = create_app(
        {
            "DATABASE": str(tmp_path / "l.db"),
            "SECRET_KEY": "t",
            "AUTH_MODE": "proxy",
            "BASE_URL": "https://s.example.com",
        }
    )
    c = app.test_client()
    post(c, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = c.get("/admin/", headers=USER).get_data(as_text=True)
    # the "created" notification, the row, and the details panel
    notice = html[html.index('class="form-ok"') : html.index("</p>", html.index('class="form-ok"'))]
    assert '<span class="base">https://s.example.com/</span><code class="slug">abc</code>' in notice
    sections = {
        "notice": notice,
        "row": html[html.index('<tr class="item') : html.index('<tr class="detail"')],
        "details": html[html.index('<tr class="detail"') : html.index("</tbody>")],
    }
    for name, part in sections.items():
        opens = [m.start() for m in re.finditer(r'class="mini" href="[^"]+" target="_blank"', part)]
        copies = [m.start() for m in re.finditer(r'class="mini copy" data-copy="', part)]
        assert opens and len(opens) == len(copies), name
        assert all(o < c_ for o, c_ in zip(opens, copies)), name  # open, then copy
        assert all(c_ - o < 400 for o, c_ in zip(opens, copies)), name  # directly next to each other
    assert len(re.findall(r'data-copy="', sections["notice"])) == 1
    assert (
        len(re.findall(r'data-copy="', sections["row"])) == 2
        and len(re.findall(r'data-copy="', sections["details"])) == 2
    )


def edit(client, app, which, headers=USER, **over):
    """POST the edit form of the link `which` (by slug) the way the browser does:
    target, slug and expiry are always sent."""
    row = link_row(app, which)
    data = {"target": row["target"], "slug": row["slug"], "expires_at": (row["expires_at"] or "")[:10]}
    data.update(over)
    return post(client, f"/admin/links/{row['id']}/update", headers, **data)


def link_row(app, slug):

    with app.app_context():
        return get_db().execute("SELECT * FROM links WHERE slug = ?", (slug,)).fetchone()


def test_change_expiry_of_an_existing_link(client, app):

    today = datetime.now(timezone.utc).date()
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    day = (today + timedelta(days=10)).isoformat()
    r = edit(client, app, "abc", expires_at=day, back="/admin/?status=active")
    assert r.status_code == 302 and r.headers["Location"] == "/admin/?status=active"
    assert link_row(app, "abc")["expires_at"] == f"{day}T23:59:59Z"
    assert day in client.get("/admin/", headers=USER).get_data(as_text=True)
    # empty value removes the expiry again
    edit(client, app, "abc", expires_at="")
    assert link_row(app, "abc")["expires_at"] is None


def test_expiry_edit_reactivates_an_expired_link(client, app):

    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    expire(app, "abc")
    assert client.get("/abc").status_code == 404
    day = (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()
    edit(client, app, "abc", expires_at=day)
    assert client.get("/abc").status_code == 302


def test_expiry_edit_rejects_bad_dates_and_other_users(client, app):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    before = link_row(app, "abc")["expires_at"]
    for bad, message in (("31/12/2030", "must be a date"), ("tomorrow", "must be a date")):
        r = edit(client, app, "abc", expires_at=bad)
        assert r.status_code == 302
        assert link_row(app, "abc")["expires_at"] == before
        assert message in client.get("/admin/", headers=USER).get_data(as_text=True)  # shown once, then gone
    assert edit(client, app, "abc", headers=USER2, expires_at="2099-01-01").status_code == 404
    assert edit(client, app, "abc", headers=ADMIN, expires_at="2099-01-01").status_code == 302
    assert link_row(app, "abc")["expires_at"] == "2099-01-01T23:59:59Z"


# ---------------------------------------------------------------- details layout, brand, icon spacing
def test_details_order_full_url_and_expiry_switch(client, app):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="plain")
    post(client, "/admin/links", USER, target="https://example.com/u", slug="dated", expires_at="2099-01-01")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    details = {m.group(1): m.group(0) for m in re.finditer(r'<tr class="detail" id="d(\d+)".*?</tr>', html, re.S)}
    plain, dated = details["1"], details["2"]
    order = [plain.index(f"<dt>{t}</dt>") for t in ("Created by", "Created", "Expires", "Target", "Short link")]
    assert order == sorted(order)  # what the collapsed row doesn't show comes first
    assert '<span class="slug-prefix">http://localhost/</span>' in plain  # fully qualified, then the editable slug
    assert re.search(r'name="slug" form="x1"[^>]*value="plain"', plain) and re.search(
        r'name="target" form="x1"[^>]*value="https://example.com/t"', plain
    )
    assert "hint-inline" not in plain and "Never expires" not in plain  # no explanation text any more
    # the switch controls the date field: off = disabled (and therefore not sent), on = required
    assert 'class="expiry-switch"' in plain and re.search(r'name="expires_at"[^>]*\bdisabled\b', plain)
    assert (
        'class="expiry-switch"' in dated
        and "checked" in dated
        and re.search(r'name="expires_at"[^>]*\brequired\b', dated)
    )


def test_collapsed_row_shows_slug_without_slash_as_code(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    row = client.get("/admin/", headers=USER).get_data(as_text=True)
    row = row[row.index('<tr class="item') : row.index('<tr class="detail"')]
    assert '<code class="slug">abc</code>' in row and '<span class="url truncate"' in row
    assert ">/abc<" not in row


def test_disabled_date_clears_the_expiry(client, app):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc", expires_at="2099-01-01")
    link_id = link_row(app, "abc")["id"]
    assert link_row(app, "abc")["expires_at"]
    post(
        client, f"/admin/links/{link_id}/update", USER, target="https://example.com/t", slug="abc"
    )  # a disabled date is not submitted at all
    assert link_row(app, "abc")["expires_at"] is None


def test_icons_share_one_wrapper_and_header_has_tagline(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert html.count('class="link-actions"') == html.count('data-copy="') >= 4
    assert '<span class="tagline">URL Shortener</span>' in html
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert css_rule(css, ".tagline")["font"] == "600 10px/1 var(--font-text)"  # 10px Geist


# ---------------------------------------------------------------- column order, no-reload hooks
def test_row_columns_chevron_switch_slug(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    head = html[html.index("<thead>") : html.index("</thead>")]
    assert re.match(r"<thead><tr>\s*<th></th><th></th>\s*<th", head)  # two empty headers, then "Short link"
    assert len(re.findall(r"<th[ >]", head)) == 5
    row = html[html.index('<tr class="item') : html.index('<tr class="detail"')]
    assert re.findall(r"<td class=\"([^\"]*)\">", row) == [
        "narrow lead",
        "narrow",
        "col-slug nowrap",
        "col-target target",
        "col-visits num mono",
    ]
    cells = row.split("</td>")
    assert 'class="mini expand"' in cells[0] and 'class="slug"' not in cells[0]  # chevron alone, first
    assert 'class="row-switch"' in cells[1] and "toggle" in cells[1]  # enable switch second
    assert 'class="slug"' in cells[2]  # then the short link


def test_forms_are_wired_for_updates_without_reloads(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    post(client, "/admin/rules", ADMIN, pattern="gh/*", target="https://github.com/{1}")
    links = client.get("/admin/", headers=USER).get_data(as_text=True)
    rules = client.get("/admin/rules", headers=ADMIN).get_data(as_text=True)
    for html in (links, rules):
        assert 'id="flashes"' not in html and ".submit()" not in html and "onchange" not in html
    assert 'id="links-results"' in links and 'id="new-link-notices"' in links and 'id="new-link-error"' in links
    assert 'id="rules-results"' in rules and "data-reset-on-success" in rules
    app_js = js_source(client)
    assert "requestSubmit" in app_js and "swapRegion" in app_js and "form.submit()" not in app_js


# ---------------------------------------------------------------- notices live in their own card
def notice_box(html, scope):
    start = html.index(f'id="{scope}-notices"')
    return html[start : html.index("</div>", start)]


def link_note(client, link_id, html=None):
    """The text of the notice in a link's details, tags removed."""
    html = html or client.get("/admin/", headers=USER).get_data(as_text=True)
    box = notice_box(html, f"link-{link_id}").split(">", 1)[1]
    return html_lib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", box))).strip()


def test_messages_appear_in_the_card_they_belong_to(client, app):

    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    link_id = link_row(app, "abc")["id"]
    day = (datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat()

    edit(client, app, "abc", expires_at=day)
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert f"abc updated · expires {day}" in link_note(client, link_id, html) and 'class="form-ok"' in notice_box(
        html, f"link-{link_id}"
    )
    assert 'id="flashes"' not in html and 'class="flash' not in html
    assert "updated" not in notice_box(html, "new-link")

    edit(client, app, "abc", expires_at="31/12/2030")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert "must be a date" in link_note(client, link_id, html) and 'class="form-error"' in notice_box(
        html, f"link-{link_id}"
    )

    post(client, "/admin/rules", ADMIN, pattern="x", target="javascript:alert(1)")
    html = client.get("/admin/rules", headers=ADMIN).get_data(as_text=True)
    assert "http" in notice_box(html, "rules") and 'class="form-error"' in notice_box(html, "rules")
    assert notice_box(html, "fallback").count("<p") == 0

    post(client, "/admin/settings/fallback", ADMIN, fallback_url="https://example.com/oops")
    html = client.get("/admin/rules", headers=ADMIN).get_data(as_text=True)
    assert "Fallback saved." in notice_box(html, "fallback") and notice_box(html, "rules").count("<p") == 0
    post(client, "/admin/settings/fallback", ADMIN, fallback_url="nope")
    html = client.get("/admin/rules", headers=ADMIN).get_data(as_text=True)
    assert 'class="form-error"' in notice_box(html, "fallback")


def test_only_the_compact_short_link_is_highlighted(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    table = html[html.index("<tbody>") : html.index("</tbody>")]
    assert table.count("<code") == 1 and '<code class="slug">' in table  # chip for the compact slug only
    assert '<span class="url' in table


def test_unusual_url_warning_is_wired(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert 'id="new-link-submit"' in html and "</svg>Create</button>" in html and "novalidate" in html
    js = js_source(client)
    assert "function unusualUrl" in js and "data-warn" in js and "anyway" not in js  # the button keeps its verb
    assert "markSubmit" not in js and "new-link-submit use" not in js  # ... and its icon
    css = client.get("/static/style.css").get_data(as_text=True)
    assert ".form-warn" in css and "--warn" in css and "input[data-warn]:focus" in css


# ---------------------------------------------------------------- details grid and buttons
def test_details_layout_buttons_and_edit_form(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    d = html[html.index('<tr class="detail"') : html.index("</tbody>")]
    # two flexible rows: the facts first, then the two editable fields
    rows = re.findall(r'<dl class="details-row">(.*?)</dl>', d, re.S)
    assert [re.findall(r"<dt>([^<]+)</dt>", r) for r in rows] == [
        ["Created by", "Created", "Expires"],
        ["Target", "Short link"],
    ]
    assert "Save" not in d
    # one form for everything editable; Update belongs to it through the form attribute
    assert re.search(
        r'<form id="x1"[^>]*class="inline-form edit-form" novalidate', d
    )  # messages appear in the card, not as tooltips
    assert (
        d.count('form="x1"') == 3
        and re.search(r'name="target" form="x1"', d)
        and re.search(r'name="slug" form="x1"', d)
    )
    assert re.search(
        r'<button type="submit" form="x1" class="btn small" disabled><svg[^>]*>.*?</svg>Update</button>', d
    )
    assert re.search(
        r'<button type="button" class="btn small" data-discard="x1" hidden disabled>'
        r"<svg[^>]*>.*?</svg>Discard</button>",
        d,
    )
    # order: Delete, Discard, Update
    assert d.index("Delete</button>") < d.index("data-discard") < d.index('form="x1" class="btn small"')
    css = client.get("/static/style.css").get_data(as_text=True)
    assert css_rule(css, ".link-actions")["gap"] == "1px"
    assert (
        css_rule(css, ".details-row").items() >= {"display": "flex", "flex-wrap": "wrap"}.items()
        and "repeat(6, minmax(0, 1fr))" not in css
    )  # no fixed grid
    assert css_rule(css, "tr.detail td")["padding"] == "var(--box-pad)"  # margins around the details
    js = js_source(client)
    assert "function syncEdit" in js and "data-discard" in js and "function linkProblem" in js


# ---------------------------------------------------------------- one button language
def all_buttons(html):
    return re.findall(r'<(button|a) ([^>]*class="btn[ "][^>]*)>(.*?)</\1>', html, re.S)


def test_every_button_has_an_icon_and_a_single_verb(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    post(client, "/admin/rules", ADMIN, pattern="gh/*", target="https://github.com/{1}")
    pages = [
        client.get("/admin/", headers=USER).get_data(as_text=True),
        client.get("/admin/rules", headers=ADMIN).get_data(as_text=True),
    ]
    seen = set()
    for html in pages:
        buttons = all_buttons(html)
        assert len(buttons) >= 6
        for _tag, _attrs, inner in buttons:
            assert "<svg" in inner, inner  # every button has an icon
            words = re.sub(r"<[^>]+>", " ", inner).split()
            assert len(words) <= 1, words  # ... and a single word (icon-only buttons have none)
            seen.update(words)
    assert {"Create", "Reset", "Update", "Discard", "Delete", "Add", "Save", "Set", "Cancel"} <= seen | {"Cancel"}
    assert (
        "Discard changes" not in "".join(pages)
        and "Delete link</button>" not in "".join(pages)
        and "Add rule</button>" not in "".join(pages)
    )


def test_details_buttons_neutral_except_the_red_delete(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    css = client.get("/static/style.css").get_data(as_text=True)
    assert css_rule(css, ".btn.danger")["color"] == "var(--err)"  # delete buttons are red again
    assert re.search(
        r"\.btn\.solid-danger \{[^}]*background: var\(--err\)", css
    )  # ... also the dialog's confirm button
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    actions = html[html.index('class="detail-actions"') : html.index("</tr>", html.index('class="detail-actions"'))]
    classes = re.findall(r'<button [^>]*class="(btn[^"]*)"', actions)
    assert classes == ["btn small danger", "btn small", "btn small"]  # Delete: red; Discard, Update: neutral
    assert 'class="btn solid-danger" id="confirm-yes"' in html


def test_details_row_uses_the_full_width_and_has_no_empty_cells(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    detail = html[html.index('<tr class="detail"') : html.index("</tr>", html.index('<tr class="detail"'))]
    assert re.findall(r"<td[^>]*>", detail) == ['<td colspan="5">']  # no leading empty columns


# ---------------------------------------------------------------- editing target and short link
def test_edit_target_and_slug(client, app):
    post(client, "/admin/links", USER, target="https://example.com/old", slug="abc")
    for _ in range(3):
        client.get("/abc")
    r = edit(client, app, "abc", target="https://example.com/new?x=1", slug="renamed", back="/admin/?sort=slug")
    assert r.status_code == 302 and r.headers["Location"] == "/admin/?sort=slug"
    row = link_row(app, "renamed")
    assert (
        row["target"] == "https://example.com/new?x=1" and row["visits"] == 3 and row["created_by"] == "alice"
    )  # same link, just renamed
    assert client.get("/abc").status_code == 404  # the old short link is gone
    assert client.get("/renamed").headers["Location"] == "https://example.com/new?x=1"
    note = link_note(client, row["id"])
    assert (
        "renamed updated · new slug · new target https://example.com/new?x=1" in note and "was" not in note
    )  # the new short link, then what changed


def test_edit_rejections_keep_the_link_unchanged(client, app):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="aaa")
    post(client, "/admin/links", USER, target="https://example.com/b", slug="bbb")
    cases = [
        ({"slug": "bbb"}, "already taken"),
        ({"slug": "static"}, "reserved"),
        ({"slug": "admin"}, "reserved"),
        ({"slug": "bad slug!"}, "Slug: letters"),
        ({"slug": ""}, "Slug: letters"),
        ({"target": "javascript:alert(1)"}, "http:// or https://"),
        ({"target": ""}, "http:// or https://"),
    ]
    for over, message in cases:
        assert edit(client, app, "aaa", **over).status_code == 302
        row = link_row(app, "aaa")
        assert message in link_note(client, row["id"]), over
        assert (row["slug"], row["target"]) == ("aaa", "https://example.com/a")


def test_edit_permissions(client, app):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="aaa")
    assert edit(client, app, "aaa", headers=USER2, slug="stolen").status_code == 404
    assert link_row(app, "aaa") is not None
    assert edit(client, app, "aaa", headers=ADMIN, slug="by-admin").status_code == 302
    assert link_row(app, "by-admin")["created_by"] == "alice"


def test_past_expiry_dates_are_accepted_when_editing(client, app):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="aaa")
    expire(app, "aaa")
    assert edit(client, app, "aaa", target="https://example.com/fixed").status_code == 302  # unchanged past date: fine
    row = link_row(app, "aaa")
    assert row["target"] == "https://example.com/fixed" and row["expires_at"] == "2000-01-01T23:59:59Z"
    edit(client, app, "aaa", expires_at="2000-02-02")  # another past date: the page warns, the server accepts
    assert link_row(app, "aaa")["expires_at"] == "2000-02-02T23:59:59Z"


# ---------------------------------------------------------------- delete dialog
def test_delete_dialog_shows_both_urls_alike_with_an_arrow(client):
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    p = html[html.index('id="confirm-text"') : html.index("</p>", html.index('id="confirm-text"'))]
    assert re.search(
        r'<span id="confirm-name"></span><svg class="icon"[^>]*><use href="[^"]*#arrow"/></svg>'
        r'<span id="confirm-detail"></span>',
        p,
    )
    css = client.get("/static/style.css").get_data(as_text=True)
    assert css_rule(css, ".confirm-urls code.slug")["font-size"] == "13px" and "rotate(90deg)" in css
    assert (
        css_rule(css, ".slug-group input.url-input")["font-family"] == "var(--font-mono)"
    )  # only the slug field is mono
    assert "→" not in js_source(client)  # the arrow is an icon now


def test_created_time_is_a_localizable_element_with_the_utc_original_as_tooltip(client, app):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    created = link_row(app, "abc")["created_at"]  # e.g. 2026-11-25T09:07:53Z
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    original = created.replace("T", " ").replace("Z", " UTC")
    assert (
        f'<time class="localtime" datetime="{created}" title="{original}">{created[:16].replace("T", " ")}</time>'
        in html
    )  # date and time without JavaScript, the UTC moment on hover
    js = js_source(client)
    assert "function localizeTimes" in js and js.count("localizeTimes()") >= 2  # on load and after table swaps


# ---------------------------------------------------------------- slug generator


def created_slug(client, headers=USER, **data):
    """Create a link and return the slug the server picked."""
    r = post(client, "/admin/links", headers, target="https://example.com/g", **data)
    assert r.status_code == 302, r.get_data(as_text=True)[:300]
    return re.search(
        r"data-copy=\"http://localhost/([^\"]+)\"", client.get("/admin/", headers=headers).get_data(as_text=True)
    ).group(1)


def test_generate_with_the_default_alphabet(client):
    assert not set("il1o0") & set(ALPHABETS["default"])  # no look-alikes
    seen = set()
    for _ in range(15):
        slug = created_slug(client, slug_mode="generate", alphabet="default", length="8")
        assert len(slug) == 8 and set(slug) <= set(ALPHABETS["default"])
        seen.add(slug)
    assert len(seen) == 15  # actually random


def test_generate_letters_only_and_custom_alphabets(client):
    slug = created_slug(client, slug_mode="generate", alphabet="letters", length="12")
    assert len(slug) == 12 and slug.isalpha() and slug.islower()
    slug = created_slug(client, slug_mode="generate", alphabet="custom", alphabet_custom="xyz789", length="10")
    assert len(slug) == 10 and set(slug) <= set("xyz789")
    # symbols are fine in the alphabet and anywhere in the slug, including the first position
    firsts = set()
    for _ in range(30):
        slug = created_slug(client, slug_mode="generate", alphabet="custom", alphabet_custom="-_a", length="6")
        assert set(slug) <= set("-_a")
        firsts.add(slug[0])
    assert firsts - {"a"}  # a symbol did come first at least once


def test_generator_validation(client):
    bad = [
        ({"slug_source": "chars", "alphabet_custom": "a"}, "alphabet_custom"),  # needs two different characters
        ({"slug_source": "chars", "alphabet_custom": "aaaa"}, "alphabet_custom"),
        ({"slug_source": "chars", "alphabet_custom": "ab c"}, "alphabet_custom"),  # a space would break the URL
        ({"slug_source": "chars", "alphabet_custom": "ab/"}, "alphabet_custom"),
        ({"slug_source": "chars", "alphabet_custom": "a?b#"}, "alphabet_custom"),
        ({"slug_source": "klingon"}, "slug_source"),
        ({"slug_source": "default", "length": "2"}, "length"),
        ({"slug_source": "letters", "length": "33"}, "length"),
        ({"slug_source": "default", "length": "x"}, "length"),
        ({"slug_source": "slug", "slug": ""}, "slug"),
        ({"slug_source": "slug", "slug": "a b"}, "slug"),
    ]
    for extra, field in bad:
        r = post(client, "/admin/links", USER, target="https://example.com/g", **extra)
        html = r.get_data(as_text=True)
        assert r.status_code == 400 and re.search(rf'name="{field}"[^>]*aria-invalid="true"', html), (extra, html[:200])
    assert "No links yet." in client.get("/admin/", headers=USER).get_data(as_text=True)
    # older posts (slug_mode + alphabet) are still understood
    r = post(client, "/admin/links", USER, target="https://example.com/g", slug_mode="generate", alphabet="klingon")
    assert r.status_code == 400 and re.search(r'name="slug_source"[^>]*aria-invalid="true"', r.get_data(as_text=True))


def test_slug_mode_decides_what_is_used(client):
    assert created_slug(client, slug_mode="custom", slug="mine") == "mine"
    r = post(client, "/admin/links", USER, target="https://example.com/g", slug_mode="custom", slug="")
    assert r.status_code == 400 and "Enter a slug" in r.get_data(as_text=True)
    other = created_slug(
        client, slug_mode="generate", slug="ignored", length="6"
    )  # a typed slug is ignored when generating
    assert other != "ignored" and len(other) == 6
    assert len(created_slug(client)) == 5  # no mode, no slug: default alphabet, length 5


def test_generator_gives_up_politely_when_the_alphabet_is_exhausted(client):
    # "ab" with length 3 has exactly 8 combinations: take them all, then ask for one more
    for combo in ("aaa", "aab", "aba", "abb", "baa", "bab", "bba", "bbb"):
        assert (
            post(
                client, "/admin/links", USER, target="https://example.com/g", slug_mode="custom", slug=combo
            ).status_code
            == 302
        )
    r = post(
        client,
        "/admin/links",
        USER,
        target="https://example.com/g",
        slug_mode="generate",
        alphabet="custom",
        alphabet_custom="ab",
        length="3",
    )
    html = r.get_data(as_text=True)
    assert (
        r.status_code == 400
        and "No free slug found" in html
        and re.search(r'name="length"[^>]*aria-invalid="true"', html)
    )


def test_new_link_form_markup_and_remembered_choice(client):
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    assert "slug_mode" not in html and "segmented" not in html  # the two-way toggle is gone
    assert re.search(
        r'<select name="slug_source" id="slug-source">\s*<option value="default" selected>Random · default</option>'
        r'\s*<option value="letters">Random · letters only</option>'
        r'\s*<option value="chars">Random · own characters</option>'
        r'\s*<option value="slug">Custom slug</option>',
        html,
    )
    assert re.search(r'name="length" type="number" value="5" min="3" max="32"', html)
    assert (
        'data-when-source="chars"' in html
        and 'data-when-source="default letters chars"' in html
        and 'data-when-source="slug"' in html
    )
    assert '<p class="alphabet-hint"' in html  # what it draws from: one line that can't overflow
    assert (
        'data-fresh="yes"' in html and "&#34;default&#34;" in html
    )  # the alphabets are handed to the page for that line
    failed = post(
        client, "/admin/links", USER, target="https://example.com/g", slug_source="chars", alphabet_custom="a"
    ).get_data(as_text=True)
    assert (
        'data-fresh="no"' in failed and '<option value="chars" selected>' in failed
    )  # the server's values win over remembered ones


# ---------------------------------------------------------------- Bitwarden-style slug colours
def test_highlight_slug_colours_digits_and_symbols():
    assert str(highlight_slug("abc")) == "abc"
    assert (
        str(highlight_slug("x9k-2_p")) == 'x<span class="hl-digit">9</span>k<span class="hl-symbol">-</span>'
        '<span class="hl-digit">2</span><span class="hl-symbol">_</span>p'
    )
    assert str(highlight_slug("a123b")) == 'a<span class="hl-digit">123</span>b'  # runs share one span
    assert "<b>" not in str(highlight_slug("<b>"))  # always escaped


def test_collapsed_row_uses_the_highlight(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="x9k-2")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    row = html[html.index('<tr class="item') : html.index('<tr class="detail"')]
    assert (
        '<code class="slug">x<span class="hl-digit">9</span>k<span class="hl-symbol">-</span>'
        '<span class="hl-digit">2</span></code>' in row
    )
    css = client.get("/static/style.css").get_data(as_text=True)
    assert css_rule(css, ".hl-digit")["color"] == "var(--accent-ink)" and (
        css_rule(css, ".hl-symbol")["color"] == "var(--err)"
    )


# ---------------------------------------------------------------- warnings stay short
def test_warning_texts_are_brief(client):
    js = js_source(client)
    assert "Unusual address:" in js and "Expiry date is in the past." in js and "again to continue" in js
    assert (
        "won't work" not in js and "(:" not in js and "odd ending (" not in js
    )  # no explanations, no values in parentheses
    assert (
        "doesn't look like a usual" not in js and "dead on arrival" not in js and "Check it, or press" not in js
    )  # the long wordings are gone
    for reason in ("uses http", "has no domain ending", "is an IP address", "has a port", "has a login", "has spaces"):
        assert reason in js


def test_update_messages_name_the_short_link_and_what_changed(client, app):
    post(client, "/admin/links", USER, target="https://example.com/old", slug="abc")
    lid = link_row(app, "abc")["id"]

    def note():
        return link_note(client, lid)

    edit(client, app, "abc", target="https://example.com/new")
    assert note() == "abc updated · new target https://example.com/new"
    edit(client, app, "abc", expires_at="2099-01-01")
    assert note() == "abc updated · expires 2099-01-01"
    edit(client, app, "abc", expires_at="")
    assert note() == "abc updated · no expiry"
    edit(client, app, "abc", target="https://example.com/x", slug="xyz", expires_at="2098-02-02")
    assert note() == "xyz updated · new slug · new target https://example.com/x · expires 2098-02-02"
    edit(client, app, "xyz")
    assert note() == "xyz is up to date"
    post(client, "/admin/links", USER, target="https://example.com/o", slug="other")
    edit(client, app, "xyz", slug="other")
    assert note() == "Slug other is already taken."  # inline, so no link name needed


# ---------------------------------------------------------------- "target already shortened" lookup
def lookup(client, headers, target, **extra):
    return client.get("/admin/links/lookup", headers=headers, query_string={"target": target, **extra}).get_json()


def test_lookup_finds_links_with_the_same_target_but_hides_other_peoples_slugs(client, app):
    post(client, "/admin/links", USER, target="https://Example.com/a/", slug="mine")
    post(client, "/admin/links", USER2, target="https://example.com/a", slug="theirs")
    post(client, "/admin/links", USER, target="https://example.com/b", slug="other")
    # trailing slash and the case of scheme/host don't matter; both links count, only visible slugs are named
    assert lookup(client, USER, "https://example.com/a") == {"count": 2, "slugs": ["mine"]}
    assert lookup(client, USER2, "https://EXAMPLE.com/a/") == {"count": 2, "slugs": ["theirs"]}
    assert lookup(client, ADMIN, "https://example.com/a") == {"count": 2, "slugs": ["mine", "theirs"]}
    # a different path, query or fragment is a different target
    for different in (
        "https://example.com/a?x=1",
        "https://example.com/a#top",
        "https://example.com/A",
        "http://example.com/a",
        "https://example.com/c",
    ):
        assert lookup(client, USER, different)["count"] == 0, different


def test_lookup_ignores_the_link_being_edited_and_bad_input(client, app):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="mine")
    mine = link_row(app, "mine")["id"]
    assert lookup(client, USER, "https://example.com/a", exclude=mine) == {"count": 0, "slugs": []}
    assert lookup(client, USER, "javascript:alert(1)") == {"count": 0, "slugs": []}
    assert lookup(client, USER, "") == {"count": 0, "slugs": []}
    r = client.get("/admin/links/lookup", headers=USER, query_string={"target": "https://example.com/a"})
    assert r.headers["Cache-Control"] == "no-store" and r.mimetype == "application/json"


def test_lookup_requires_a_signed_in_user(client):
    assert client.get("/admin/links/lookup", query_string={"target": "https://example.com/a"}).status_code == 403


def test_forms_know_where_to_look_up_and_the_warning_is_brief(client):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="mine")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert html.count('data-lookup="/admin/links/lookup"') == 2  # the new-link form and the edit form
    assert 'data-exclude="1"' in html  # an edit never counts its own link
    js = js_source(client)
    assert "function alreadyShortened" in js and "Target already shortened" in js and "by someone else" in js
    assert "function lookupThenResubmit" in js and "needsLookup(form)" in js


# ---------------------------------------------------------------- search language on the page
def seed_query_links(client, app):
    post(client, "/admin/links", USER, target="https://github.com/dero", slug="aaa")
    post(client, "/admin/links", USER, target="https://example.com/blog", slug="bbb")
    post(client, "/admin/links", USER, target="https://example.com/shop", slug="ccc")
    post(client, "/admin/links", USER2, target="https://github.com/other", slug="ddd")
    post(client, "/admin/links", USER2, target="https://news.example.org/", slug="eee")
    for _ in range(4):
        client.get("/aaa")
    client.get("/bbb")  # one visit, then it expires
    expire(app, "bbb")
    post(client, f"/admin/links/{link_row(app, 'ccc')['id']}/toggle", USER)  # ccc: disabled


def shown(client, headers, q):
    return slugs(client, headers, "?" + "&".join(f"q={__import__('urllib.parse').parse.quote(q)}" for _ in [0]))


def test_query_param_filters_and_sorts(client, app):
    seed_query_links(client, app)
    assert sorted(shown(client, ADMIN, "status=expired")) == ["bbb"]
    assert sorted(shown(client, ADMIN, "status=disabled,expired")) == ["bbb", "ccc"]
    assert sorted(shown(client, ADMIN, "creator=bob")) == ["ddd", "eee"]
    assert sorted(shown(client, ADMIN, "github !creator=bob")) == ["aaa"]
    assert sorted(shown(client, ADMIN, "(creator=bob or status=expired) github")) == ["ddd"]
    assert shown(client, ADMIN, "creator=alice sortby=visits")[:2] == ["aaa", "bbb"]  # most visits first
    assert shown(client, ADMIN, "creator=alice sortby=+visits")[-1] == "aaa"  # + is ascending: fewest first
    assert shown(client, ADMIN, "creator=alice sortby=-visits") == shown(client, ADMIN, "creator=alice sortby=visits")
    assert shown(client, ADMIN, "sortby=slug")[:2] == ["aaa", "bbb"] and shown(client, ADMIN, "sortby=-slug")[:2] == [
        "eee",
        "ddd",
    ]
    assert shown(client, ADMIN, "sortby=+slug") == shown(client, ADMIN, "sortby=slug")  # A to Z is its usual order
    assert sorted(shown(client, ADMIN, "status=nonsense")) == []


def test_a_query_can_never_widen_what_a_user_sees(client, app):
    seed_query_links(client, app)
    for q in (
        "creator=bob",
        "creator=bob or creator=alice",
        "!creator=alice",
        "(creator=bob)",
        "ddd",
        "status=active or creator=bob",
        "github",
    ):
        assert not {"ddd", "eee"} & set(shown(client, USER, q)), q  # alice never sees bob's links
        assert not {"aaa", "bbb", "ccc"} & set(shown(client, USER2, q)), q
    assert sorted(shown(client, USER, "github")) == ["aaa"]


def test_old_style_parameters_still_work_and_show_up_as_a_query(client, app):
    seed_query_links(client, app)
    html = client.get("/admin/?status=expired&owner=alice&order=visits:asc", headers=ADMIN).get_data(as_text=True)
    assert 'value="status=expired created_by=alice sort_by=+visits"' in html
    assert re.findall(r'class="slug">([a-z]+)</code>', html) == ["bbb"]


def test_problems_are_shown_briefly_above_the_table(client, app):
    seed_query_links(client, app)
    html = client.get("/admin/", headers=ADMIN, query_string={"q": "status=nonsense (sortby=colour"}).get_data(
        as_text=True
    )
    line = html[
        html.index('class="form-warn query-problems"') : html.index(
            "</p>", html.index('class="form-warn query-problems"')
        )
    ]
    assert "Unknown status: nonsense" in line and "Unknown sort: colour" in line and "Missing )" in line
    assert "query-problems" not in client.get("/admin/", headers=ADMIN, query_string={"q": "status=expired"}).get_data(
        as_text=True
    )


def test_filter_bar_markup(client, app):
    seed_query_links(client, app)
    html = flat(
        client.get("/admin/", headers=ADMIN, query_string={"q": "status=expired sortby=+visits"}).get_data(as_text=True)
    )
    assert 'value="status=expired sortby=+visits"' in html and 'class="qhighlight"' in html and 'id="q-help"' in html
    assert re.search(r'<details class="multi" id="filter-status" data-key="status"', html)
    assert re.findall(
        r'<input type="checkbox" value="(\w+)" checked><span>(\w+)</span>',
        html[html.index('id="filter-status"') : html.index('id="filter-creator"')],
    ) == [("active", "Active"), ("disabled", "Disabled"), ("expired", "Expired")]
    creators = html[html.index('id="filter-creator"') : html.index('<label class="field-label" for="filter-sort">')]
    assert re.findall(r'<input type="checkbox" value="([^"]+)"', creators) == ["alice", "bob"]
    # the sort dropdown holds sortby values; the current one is selected
    assert (
        '<option value="+visits" selected>Fewest visits</option>' in html
        and '<option value="">Newest first</option>' in html
    )
    # sortable headers carry the new query; Reset goes back to the plain page
    assert (
        'href="/admin/?q=status%3Dexpired+sort_by%3Dvisits"' in html
        or 'href="/admin/?q=status%3Dexpired%20sort_by%3Dvisits"' in html
    )
    assert re.search(r'id="reset-filters" href="/admin/"', html) and 'aria-disabled="false"' in html
    # people who can't see others have no "created by" dropdown
    assert 'id="filter-creator"' not in client.get("/admin/", headers=USER).get_data(as_text=True)
    assert (
        "sortby" not in html.split("<tbody>")[0].split("data-sort-keys")[0]
    )  # (the attribute names, not values, carry the keys)


def test_toggle_and_delete_return_to_the_query_view(client, app):
    seed_query_links(client, app)
    back = "/admin/?q=status%3Dactive+sortby%3Dvisits"
    html = client.get(back, headers=ADMIN).get_data(as_text=True)
    assert f'name="back" value="{back}"' in html
    r = post(client, f"/admin/links/{link_row(app, 'aaa')['id']}/toggle", ADMIN, back=back)
    assert r.headers["Location"] == back


# ---------------------------------------------------------------- slugs may start with - or _
def test_slugs_may_use_any_character_a_url_does_not_need_to_escape(client, app):
    for slug in ("---", "_", "-a", "__init__", "a-b_c", "-" * 64, "a.b", "v1.2.3", ".hidden", "a~b", "~", "..a", "a.."):
        assert post(client, "/admin/links", USER, target="https://example.com/t", slug=slug).status_code == 302, slug
        assert client.get(f"/{slug}").status_code == 302, slug
    assert (
        edit(client, app, "---", slug="-_.~-").status_code == 302 and client.get("/-_.~-").status_code == 302
    )  # renaming to one works too
    for bad in ("", "a b", "a/b", "a?b", "a#b", "a%41", "a&b", "a+b", "a:b", "a@b", "ä", "x" * 65):
        r = post(client, "/admin/links", USER, target="https://example.com/t", slug_source="slug", slug=bad)
        assert r.status_code == 400, bad
    for dots in (".", "..", "....."):
        r = post(client, "/admin/links", USER, target="https://example.com/t", slug_source="slug", slug=dots)
        assert r.status_code == 400 and "can&#39;t be just dots" in r.get_data(as_text=True), (
            dots
        )  # browsers fold "/." and "/.." away
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert (
        html.count('pattern="[A-Za-z0-9._~\\-]{1,64}"') == html.count('name="slug"') >= 2
    )  # the browser pattern agrees
    assert "Slug: letters, digits and - _ . ~ only, up to 64." in js_source(client)


# ---------------------------------------------------------------- columns the user can switch on and off
def table_columns(html):
    head = html[html.index("<thead>") : html.index("</thead>")]
    return re.findall(r'<th class="(col-\w+)', head)


def test_default_columns_are_the_current_ones(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    assert table_columns(html) == ["col-slug", "col-target", "col-visits"]
    assert 'id="filter-columns"' in html and '<span class="multi-label">3 of 6</span>' in html
    assert re.findall(
        r'<input type="checkbox" value="(\w+)"( checked)?><span>([^<]+)</span>',
        html[html.index('id="filter-columns"') : html.index('id="reset-filters"')],
    ) == [
        ("slug", " checked", "Slug"),
        ("target", " checked", "Target"),
        ("creator", "", "Created by"),
        ("created", "", "Created"),
        ("expires", "", "Expires"),
        ("visits", " checked", "Visits"),
    ]


def test_the_cookie_chooses_the_columns(client, app):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc", expires_at="2099-05-06")
    client.set_cookie(
        "dero_cols", "slug,creator,created,expires,visits,bogus,target"
    )  # order in the cookie doesn't matter, junk is ignored
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert table_columns(html) == ["col-slug", "col-target", "col-creator", "col-created", "col-expires", "col-visits"]
    row = html[html.index('<tr class="item') : html.index('<tr class="detail"')]
    assert (
        '<td class="col-creator nowrap">alice</td>' in row
        and 'data-day datetime="2099-05-06T23:59:59Z" title="2099-05-06 UTC">2099-05-06</time>' in row
    )
    assert re.search(
        r'<td class="col-created nowrap mono"><time class="localtime" datetime="[^"]+" title="[^"]+ UTC">'
        r"\d{4}-\d\d-\d\d \d\d:\d\d</time></td>",
        row,
    )
    assert '<span class="multi-label">6 of 6</span>' in html
    # what is a column is not repeated in the details; the editable expiry always stays there
    detail = html[html.index('<tr class="detail"') : html.index("</tbody>")]
    assert "<dt>Created by</dt>" not in detail and "<dt>Created</dt>" not in detail and "<dt>Expires</dt>" in detail
    assert 'colspan="8"' in detail  # 2 fixed + 6 columns


def test_columns_can_be_reduced_and_the_footer_follows(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    client.set_cookie("dero_cols", "target")
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    assert table_columns(html) == ["col-target"] and "<tfoot>" not in html  # no visits column, no total row
    client.set_cookie("dero_cols", "creator,visits")
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    assert re.search(
        r'<tfoot><tr><td colspan="3">Total visits</td><td class="num mono">0</td></tr></tfoot>', html
    )  # the total sits under Visits
    client.delete_cookie("dero_cols")
    assert table_columns(client.get("/admin/", headers=USER).get_data(as_text=True)) == [
        "col-slug",
        "col-target",
        "col-visits",
    ]


def test_new_columns_are_sortable_and_the_expired_badge_follows_the_icons(client, app):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    expire(app, "abc")
    client.set_cookie("dero_cols", "slug,expires,created,creator")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert "sort_by%3Dexpires" in html and "sort_by%3Dcreator" in html  # new sort links for the new columns
    assert "sort_by%3D%2Bcreated" in html  # (created is the current sort, so its link reverses it: oldest first)
    row = html[html.index('<tr class="item') : html.index('<tr class="detail"')]
    assert row.index("link-actions") < row.index('class="expired-mark"')  # the clock comes after the open/copy icons
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert "--control-h: 30px" in css and re.search(
        r"td\.col-target \{ width: 100%; max-width: 0; min-width: 12rem; \}", css
    )


# ---------------------------------------------------------------- one dropdown style, coloured search terms
def test_selects_are_plain_in_the_html_and_upgraded_by_the_script(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    rules = client.get("/admin/rules", headers=ADMIN).get_data(as_text=True)
    assert (
        '<select id="filter-sort">' in html
        and '<select name="slug_source" id="slug-source"' in html
        and '<select name="match_type">' in rules
    )  # work without JavaScript
    js = js_source(client)
    assert 'document.querySelectorAll("select").forEach(upgradeSelect)' in js and "function refreshSelect" in js
    assert (
        'className = "multi single"' in js and 'role", "listbox"' in js
    )  # same details/summary component as the checkbox lists
    assert js.count('querySelectorAll("details.multi[open]")') == 2  # one outside-click and one Escape handler for all
    css = client.get("/static/style.css").get_data(as_text=True)
    assert "select.native-hidden" in css and ".multi-panel .option" in css and ".single-panel" in css


def test_search_terms_have_a_colour_per_kind_and_room_between_them(client):
    js = js_source(client)
    assert "q-term q-k-${t.key}" in js and "q-term q-k-text" in js  # every term kind gets its own class
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    for kind in ("text", "status", "creator", "slug", "target", "sortby"):
        assert re.search(rf"\.q-k-{kind} \{{ --c: var\(--q-{kind}\); \}}", css), kind
    colours = re.search(
        r":root \{ --q-text: var\(--muted\); --q-status: (#\w+); --q-creator: (#\w+);"
        r" --q-slug: (#\w+); --q-target: (#\w+);",
        css,
    ).groups()
    assert len(set(colours)) == 4  # four different hues (plus muted and the secondary colour)
    assert re.search(
        r"\.qhighlight, \.qfield input\.qinput, \.qfield input\.qinput:focus \{ word-spacing: 17px; \}", css
    )  # same spacing in both layers
    assert re.search(r"\.filters > \.field\.grow \{ flex: 1 1 100%; \}", css)  # the search bar has its own row


# ------------------------------------------------------- generator: repeats are weights, URL-safe characters only
def test_a_repeated_character_is_more_likely():

    sample = "".join(random_slug("aaab", 20) for _ in range(300))  # 6000 characters, "a" three times as likely as "b"
    share = sample.count("a") / len(sample)
    assert 0.70 < share < 0.80, share


def test_generating_from_own_characters_keeps_duplicates_and_allows_dots_and_tildes(client):
    made = set()
    for _ in range(12):
        made.add(created_slug(client, slug_source="chars", alphabet_custom="aaa..~~b", length="12"))
    assert all(len(s) == 12 and set(s) <= set("a.~b") for s in made) and len(made) == 12
    assert not any(set(s) == {"."} for s in made)
    # a slug that would be folded away by browsers is never generated: only "..." and ".." style slugs are possible here
    for _ in range(3):  # (7 combinations are valid, so a free one is always found)
        slug = created_slug(client, slug_source="chars", alphabet_custom="..~", length="3")
        assert set(slug) != {"."} and set(slug) <= set(".~")


def test_new_source_field_decides_what_is_used(client):
    assert created_slug(client, slug_source="slug", slug="mine") == "mine"
    assert created_slug(client, slug_source="slug", slug="a.b~c") == "a.b~c"
    other = created_slug(
        client, slug_source="default", slug="ignored", length="6"
    )  # a typed slug is ignored when generating
    assert other != "ignored" and len(other) == 6
    assert set(created_slug(client, slug_source="letters", length="9")) <= set("abcdefghijklmnopqrstuvwxyz")


# ---------------------------------------------------------------- remove-x in the search bar, expired mark
def test_search_bar_has_a_layer_for_the_remove_buttons(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert '<div class="qx-layer"></div>' in html
    js = js_source(client)
    assert "function removePart" in js and "function drawRemovers" in js and 'className = "qx"' in js
    assert "tabIndex = -1" in js and "Remove ${label}" in js  # mouse helper; the keyboard edits the text
    css = client.get("/static/style.css").get_data(as_text=True)
    assert ".qx-layer" in css and css_rule(css, ".qx:hover, .qx:focus-visible")["color"] == "var(--err)"


def test_expired_mark_is_a_clock_with_the_date_not_a_text_badge(client, app):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    expire(app, "abc")
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    mark = re.search(
        r'<span class="expired-mark" data-expired="[^"]+" role="img" aria-label="([^"]+)" title="([^"]+)">'
        r"(<svg.*?</svg>)</span>",
        html,
    )
    assert mark and mark.group(1) == mark.group(2) == "Expired on 2000-01-01" and "#clock" in mark.group(3)
    assert "badge" not in html.split("<tbody>")[1].split("</tbody>")[0]
    post(client, "/admin/links", USER, target="https://example.com/u", slug="fine")
    two = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert (
        two.count('class="expired-mark"') == 1 and two.count('<tr class="item') == 2
    )  # only the expired link carries it


def test_slug_colour_option_and_small_expiry_switch(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert (
        '<html lang="en" data-hl="on">' in html
        and 'id="hl-switch"' in html
        and " checked" in html[html.index('id="hl-switch"') :][:120]
    )
    client.set_cookie("dero_hl", "0")
    off = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert 'data-hl="off"' in off and " checked" not in off[off.index('id="hl-switch"') :][:120]
    assert re.search(
        r'<label class="switch small"[^>]*>\s*<input type="checkbox" role="switch" id="new-expiry-switch"', html
    )
    assert re.search(r'<input name="expires_at" type="date"[^>]*disabled', html)  # off until the switch is on
    css = client.get("/static/style.css").get_data(as_text=True)
    assert 'html[data-hl="off"] .hl-digit' in css and "table.no-target td.col-slug" in css
    js = js_source(client)
    assert "dero_hl=" in js and "function coloredSlug" in js and "new-expiry-switch" in js


def test_detail_inputs_use_card_background(client):
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert re.search(r"tr\.detail input\[type=\"text\"\][^{]*tr\.detail \.slug-group \{ background: var\(--card\)", css)


def test_code_rule_keeps_its_body_and_chips_have_the_padding(client):
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert re.search(
        r"code, \.url, \.mono, \.url-input \{ font-variant-ligatures: none;", css
    )  # (a lost body once gave every code box padding)
    assert "padding: 1px 12px 1px 5px; margin: 0 -12px 0 -5px;" in css  # chips: the x sits in the padding
    html = flat(client.get("/admin/", headers=USER).get_data(as_text=True))
    assert re.search(
        r'<label><input type="checkbox" value="active" checked><span>[^<]*</span><svg', html
    )  # checkbox dropdowns tick like the single ones


def test_generate_button_and_settings_dialog(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert 'id="new-link-generate"' in html and "Generate</button>" in html
    assert re.search(
        r'<button type="button" class="who" id="settings-open"[^>]*>.*?alice.*?</button>', html, re.S
    )  # the user name opens the settings
    dialog = html[html.index('<dialog id="settings"') : html.index("</dialog>", html.index('<dialog id="settings"'))]
    assert 'id="hl-switch"' in dialog and "Colour slugs" in dialog and 'class="header-tools"' not in html
    js = js_source(client)
    assert "function randomSlug" in js and "settings-open" in js


def test_header_has_a_plain_user_name_and_a_sun_moon_switch(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    who = re.search(r'<button type="button" class="who".*?</button>', html, re.S).group(0)
    assert re.sub(r"<[^>]+>", "", who).strip() == "alice" and "<svg" not in who and "badge" not in who
    toggle = re.search(r'<button[^>]*id="theme-toggle".*?</button>', html, re.S).group(0)
    assert 'role="switch"' in toggle and 'aria-checked="false"' in toggle
    assert toggle.index("#sun") < toggle.index("#moon")  # the sun on the left, the moon on the right
    assert "Signed in as <strong>alice</strong> (user)" in html  # the role moved into the settings dialog


def test_theme_switch_is_drawn_from_tokens_and_dropdown_rows_have_a_visible_hover(client):
    css = client.get("/static/style.css").get_data(as_text=True)
    # the knob position comes from theme tokens (set before the first paint), never from the aria-checked attribute
    # that the script sets later: that is what made the knob slide on every reload
    assert css_rule(css, ".theme-toggle::before")["left"] == "var(--toggle-knob)"
    assert "aria-checked" not in css
    assert css.count("--toggle-knob:") == 3  # light, dark by preference, dark by choice
    assert "transition" in css_rule(css, ".theme-toggle") and "transition" in css_rule(css, ".theme-toggle::before")
    # the hover of a dropdown row is a tint of the accent: --field is nearly the same as the panel on both themes
    for selector in (".multi-panel label:hover", ".multi-panel .option:hover, .multi-panel .option:focus-visible"):
        assert css_rule(css, selector)["background"] == "var(--hover)"
    assert css.count("--hover:") == 3
    assert "transition" in css_rule(css, ".multi-panel label") and "transition" in css_rule(css, ".multi-panel .option")


def test_the_browser_tokenizer_has_the_same_rules_as_the_server(client):
    js = flat_js(js_source(client))
    assert 'visits: ["visits"]' in js and 'sortby: ["="]' in js and 'SORT_ALIASES = { created_by: "creator" }' in js
    assert 'slug: ["=", "=="]' in js and 'created: ["=", "==", ...COMPARISONS]' in js
    assert "(!=|==|<=|>=|=|<|>)" in js.replace("\\", "")  # the same operators as _KEYED in query.py
    assert 'span("q-star", "*")' in js  # a wildcard of a value is drawn on its own, to be coloured
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert (
        css_rule(css, ".q-star")["color"] == "var(--accent-ink)" and css_rule(css, ".q-not")["color"] == "var(--q-not)"
    )
    assert "function deriveSort(parsed, sortKeys, defaultDesc)" in js and "sortDefaultDesc" in js  # the +/- rules
    assert "q-empty" in js and "empty: values.length === 0" in js and not re.search(r"t\.key !== \"sortby\"\)", js)
    assert css_rule(css, ".q-term.q-empty")["background"] == "none"  # no value yet: drawn as an outline
    assert css_rule(css, ".target-head")["color"] == "var(--muted)"  # the ellipsis of a cut target is grey ...
    assert css_rule(css, ".target-head > span")["color"] == "var(--text)"  # ... and the address itself is not
    assert "--c: var(--q-visits)" in css and "--q-not: #e00000" in css and css.count("--q-not:") == 3


def test_targets_lose_https_and_keep_their_end_when_the_middle_is_cut():
    def parts(url):
        box = str(target_box(url))
        return list(
            re.search(r'target-head"><span>(.*?)</span></span><span class="target-tail">(.*?)</span>', box).groups()
        )

    assert parts("https://github.com/kfmndev/podutils") == ["github.com/kfmndev", "/podutils"]  # the last path part
    assert parts("http://example.com/page") == ["example.com", "/page"]  # from the domain on, whatever the scheme
    assert parts("ftp://files.example.com/a.zip") == ["files.example.com", "/a.zip"]
    assert "".join(parts("https://user@evil.example/x")) == "user@evil.example/x"  # a login in front stays visible
    assert parts("https://example.com/") == ["", "example.com/"]  # nothing to cut off
    assert parts("https://example.com/" + "x" * 40) == ["example.com/" + "x" * 28, "x" * 12]  # no usable last part
    assert parts("https://a.com/<b>&") == ["a.com", "/&lt;b&gt;&amp;"]  # escaped
    assert 'title="https://github.com/kfmndev/podutils"' in str(target_box("https://github.com/kfmndev/podutils"))


def test_a_plus_after_an_operator_in_the_address_is_warned_about(client):
    def warned(address):
        return "stands for a space" in client.get(address, headers=USER).get_data(as_text=True)

    assert (
        warned("/admin/?q=sort_by=+visits") and warned("/admin/?q=expires%3C+30d") and warned("/admin/?q=created>+7d")
    )
    assert not warned("/admin/?q=sort_by%3D%2Bvisits")  # an encoded plus is fine
    assert not warned("/admin/?q=a+b") and not warned("/admin/?q=status%3Dactive+slug%3Dabc")  # plus as a space
    assert not warned("/admin/") and not warned("/admin/?other=sort_by=+visits")


def test_long_slugs_are_cut_in_displays_but_whole_in_the_editor(client):
    slug = "abcdefghij-klmnopqrst-uvwxyz"  # 28 characters
    post(client, "/admin/links", USER, target="https://example.com/long", slug=slug)
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert (
        f'<code class="slug" title="{slug}">abcdefghij<span class="hl-symbol">-</span>klmnopqrs…</code>' in html
    )  # 20 characters, then an ellipsis
    assert f'value="{slug}"' in html  # the edit field holds all of it
    post(client, "/admin/links", USER, target="https://example.com/long2", slug="z" * 40)
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    start = html.index('<span class="base">', html.index('id="new-link-notices"'))
    created = html[start : html.index("</code>", start)].rsplit(">", 1)[
        1
    ]  # the shown text (the full slug is in the title)
    assert created == "z" * 20 + "…"  # the message after creating cuts it as well
    js = js_source(client)
    assert "code.style.transform" in js  # only the coloured box scrolls, the clip stays put


def test_settings_dialog_closes_with_a_cross(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    dialog = html[html.index('<dialog id="settings"') : html.index("</dialog>", html.index('<dialog id="settings"'))]
    assert 'class="mini dialog-close" aria-label="Close"' in dialog and "dialog-actions" not in dialog


def test_custom_characters_errors_name_the_problem(client):
    def error(chars):
        r = post(
            client,
            "/admin/links",
            USER,
            target="https://example.com/g",
            slug_source="chars",
            alphabet_custom=chars,
            length="5",
        )
        assert r.status_code == 400
        return html_lib.unescape(r.get_data(as_text=True))

    page = error("1Il|")
    assert (
        "Characters: '|' can&#39;t" not in page
        and "Characters: '|' can't be used. Allowed are letters, digits and - _ . ~" in page
    )
    assert "Characters: 'space' " not in error("ab c") and "Characters: space can't be used" in error("ab c")
    assert "Characters: '|' and '?' can't be used" in error("ab|?")  # two: and
    assert "Characters: '|', '?' and '#' can't be used" in error("ab|?#")  # more: commas, and before the last
    assert "Characters: '|', '?', '#', '%', '\"', '<', … can't be used" in error('ab|?#%"<>')  # more than six are cut
    assert "Characters: use at least 2 different ones." in error("aaaa")
    js = js_source(client)
    assert "can't be used. Allowed are letters, digits and - _ . ~" in js and "use at least 2 different ones." in js


def test_slugs_look_the_same_in_every_message(client, app):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="a1-b")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    cell = html[html.index('<td class="col-slug') : html.index("</td>", html.index('<td class="col-slug'))]
    assert '<code class="slug">a<span class="hl-digit">1</span><span class="hl-symbol">-</span>b</code>' in cell
    r = post(client, "/admin/links", USER, target="https://example.com/b", slug="a1-b")  # error text
    assert (
        '<code class="slug">a<span class="hl-digit">1</span><span class="hl-symbol">-</span>b</code> is already taken.'
        in r.get_data(as_text=True)
    )
    post(client, "/admin/links", USER, target="https://example.com/c", slug="c2.d")  # created message
    page = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert (
        'Created <span class="base">http://localhost/</span><code class="slug">c<span class="hl-digit">2</span>'
        '<span class="hl-symbol">.</span>d</code>' in page
    )
    js = js_source(client)
    assert "function slugBox" in js and "function setRich" in js


def stream_events(client, headers, trigger=None, ticks=4):
    """Run the live stream for a few ticks; `trigger` runs after the first message and may cause visits."""
    client.application.config.update(LIVE_TICK=0.02, LIVE_MAX_TICKS=ticks)
    r = client.get("/admin/links/visits/stream", headers=headers, buffered=False)
    assert (
        r.mimetype == "text/event-stream"
        and r.headers["Cache-Control"] == "no-store"
        and r.headers["X-Accel-Buffering"] == "no"
    )
    chunks = []
    for i, chunk in enumerate(r.response):
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if i == 0 and trigger:
            trigger()
    return "".join(chunks)


def test_live_stream_pushes_visits_scoped_to_the_user(client, app):
    post(client, "/admin/links", USER, target="https://example.com/a", slug="mine")
    post(client, "/admin/links", USER2, target="https://example.com/b", slug="theirs")
    body = stream_events(client, USER, lambda: [client.get("/mine"), client.get("/mine"), client.get("/theirs")])
    assert body.startswith("retry: 3000") and "event: visit" in body
    assert '"slug": "mine"' in body and '"visits": 2' in body and '"delta": 2' in body
    assert "theirs" not in body  # another user's links are not announced
    admin_body = stream_events(client, ADMIN, lambda: client.get("/theirs"))
    assert '"slug": "theirs"' in admin_body
    quiet = stream_events(client, USER)
    assert "event:" not in quiet  # nothing happened, nothing is sent


def test_live_stream_tells_the_page_when_links_come_or_go(client, app):
    body = stream_events(
        client, USER, lambda: post(client, "/admin/links", USER, target="https://example.com/n", slug="new")
    )
    assert "event: refresh" in body


def test_live_option_markup(client):
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert 'id="live-switch"' in html and "Live visits" in html and 'data-live-url="/admin/links/visits/stream"' in html
    assert re.search(r'<tr class="item " data-id="\d+" data-visits="\d+">', html) if 'class="item' in html else True
    js = js_source(client)
    assert "new EventSource" in js and "dero:live" in js and "function poll" not in js
    assert "tr.item.visited td" in client.get("/static/style.css").get_data(as_text=True)


def test_at_least_one_column_stays(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    client.set_cookie("dero_cols", "")  # an empty choice falls back to the defaults
    assert table_columns(client.get("/admin/", headers=USER).get_data(as_text=True)) == [
        "col-slug",
        "col-target",
        "col-visits",
    ]
    client.set_cookie("dero_cols", "target")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    menu = html[html.index('id="filter-columns"') : html.index('id="reset-filters"')]
    assert (
        re.search(r'value="target" checked disabled>', menu) and menu.count(" disabled>") == 1
    )  # the only one on can't be turned off
    assert "lockLastColumn" in js_source(client)


def test_detail_buttons_are_the_last_thing_in_the_details(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    detail = html[html.index('<tr class="detail"') : html.index("</tr>", html.index('<tr class="detail"'))]
    assert (
        detail.rindex("<dl") < detail.index('id="link-1-notices"') < detail.index('class="detail-actions"')
    )  # fields, messages, then the buttons
    assert detail.index("Update</button>") > detail.index('class="detail-actions"') and detail.count("<dt>") == 5
    assert "details-top" not in detail


def test_operators_are_pills_with_the_same_padding_as_terms_and_visits_are_mono(client):
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert re.search(r"\.q-op \{ padding: 1px 12px 1px 5px; margin: 0 -12px 0 -5px;", css)
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert '<td class="col-visits num mono">' in html


def test_query_names_follow_the_dropdowns_and_the_old_ones_still_work(client, app):
    seed_query_links(client, app)
    new = shown(client, ADMIN, "created_by=bob sort_by=slug")
    assert new == shown(client, ADMIN, "creator=bob sortby=slug") == shown(client, ADMIN, "owner=bob sort=slug") and new
    html = client.get("/admin/", headers=ADMIN, query_string={"q": "created_by=bob"}).get_data(as_text=True)
    assert "q-k-creator" not in html  # (chips are drawn in the browser)
    js = js_source(client)
    assert 'creator: ["created_by", "creator", "owner", "by"]' in js
    assert 'sortby: ["sort_by", "sortby", "sort", "order"]' in js and "KEY_ALIASES[key][0]" in js


def test_operators_get_a_remove_button_too(client):
    js = js_source(client)
    assert "function removeOperator" in js and 'dataset.kind = "operator"' in js and ".q-term, .q-group, .q-op" in js
    assert "#x" in js and 'button.textContent = "×"' not in js  # an icon, not a text glyph


def test_operators_stuck_to_other_tokens_are_not_highlighted(client):
    js = js_source(client)
    assert (
        'span(apart ? "q-op" : "q-op-tight", raw)' in js
        and 'const gap = (other) => !other || other.kind === "ws"' in js
    )
    assert ".q-op-tight" in client.get("/static/style.css").get_data(as_text=True)


def test_operators_are_outlined_and_groups_are_not_tinted(client):
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert re.search(
        r"\.q-op \{ padding: 1px 12px 1px 5px; margin: 0 -12px 0 -5px; border-radius: 4px; background: none;"
        r" box-shadow: 0 0 0 1px",
        css,
    )
    assert ".q-group {" not in css and ".q-group .q-group" not in css  # parentheses and groups carry no highlight


def test_labels_use_hubot_sans_and_inputs_keep_the_text_font(client):
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert "label, .label, .field-label { font-family: var(--font-head); line-height: var(--label-lh); }" in css
    assert (
        "input[type], input:not([type]), select, textarea, .multi-panel label, details.multi > summary"
        " { font-family: var(--font-text); }" in css
    )


def test_spaces_are_added_around_parentheses_while_typing(client):
    js = js_source(client)
    assert "function spaceOut" in js and 'event.inputType?.startsWith("insert")' in js  # not when deleting


def test_row_cells_centre_their_content(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    assert re.search(r'<td class="col-slug nowrap"><span class="cell"><code class="slug">abc</code>', html)
    css = flat_css(client.get("/static/style.css").get_data(as_text=True))
    assert ".col-slug .cell" in css and "td.narrow form { margin: 0; display: flex; align-items: center; }" in css


def test_a_negated_word_keeps_its_exclamation_mark_inside_its_chip(client):
    js = flat_js(js_source(client))
    assert 'word.classList.add("q-neg"); word.append(last);' in js


def test_all_options_of_status_and_created_by_can_be_deselected(client):
    js = js_source(client)
    assert "none = checked.length === 0 && all.length > 0" in js and 'label.textContent = "None"' in js
    assert 'negated ? "!=" : "="' in js and "set.length || mine[0].negated" in js
    # what such a selection sends: everything excluded, so nothing matches
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER, query_string={"q": "status!=active,disabled,expired"}).get_data(
        as_text=True
    )
    assert "No links match." in html
