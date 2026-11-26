import re

import pytest

from dero import create_app

USER = {"Remote-User": "alice", "Remote-Groups": "dero-users"}
USER2 = {"Remote-User": "bob", "Remote-Groups": "dero-users"}
ADMIN = {"Remote-User": "root", "Remote-Groups": "dero-admins,other"}


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "t.db"), "SECRET_KEY": "test", "TESTING": True,
                       "AUTH_MODE": "proxy"})


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
    client.get("/abc"); client.get("/abc/")
    with app.app_context():
        from dero.db import get_db
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
    from dero.db import get_db
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
    post(client, "/admin/rules", ADMIN, pattern=r"(a+)+$", match_type="regex", target="https://e.com/evil", priority="1")
    import time
    t = time.time()
    assert client.get("/" + "a" * 40 + "!").status_code == 404  # catastrophic pattern is cut off
    assert time.time() - t < 2


def test_rule_validation(client):
    post(client, "/admin/rules", ADMIN, pattern="a/*", target="https://e.com/{2}")       # placeholder > groups
    post(client, "/admin/rules", ADMIN, pattern="(", match_type="regex", target="https://e.com")
    post(client, "/admin/rules", ADMIN, pattern="b", target="javascript:alert(1)")
    assert client.get("/a/x").status_code == 404 and client.get("/b").status_code == 404


def test_target_placeholder_is_escaped(client):
    post(client, "/admin/rules", ADMIN, pattern="q/*", target="https://e.com/s?q={1}")
    assert client.get("/q/a b").headers["Location"] == "https://e.com/s?q=a%20b"


def test_admin_slug_reserved(client):
    r = post(client, "/admin/links", USER, target="https://example.com", slug="admin")
    assert r.status_code == 400 and "&#39;admin&#39; is reserved." in r.get_data(as_text=True)
    assert client.get("/admin").status_code in (301, 308, 404)  # the UI, never a short link


def test_custom_admin_path(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "c.db"), "SECRET_KEY": "t", "ADMIN_PATH": "manage", "AUTH_MODE": "proxy"})
    c = app.test_client()
    assert c.get("/manage/", headers=USER).status_code == 200
    assert c.get("/admin/", headers=USER).status_code == 404


# ---------------------------------------------------------------- basic auth
import base64

from dero.passwd import main as passwd_main, make_line


def basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


@pytest.fixture
def bclient(tmp_path):
    users = tmp_path / "users.txt"
    users.write_text("# comment\n" + make_line("alice", "user", "alice-password") + "\n"
                     + make_line("root", "admin", "root-password") + "\n" + "garbage line\n")
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
    assert bclient.get("/x").status_code == 302                      # short links stay public
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
    return re.findall(r'class="slug">/([a-z]+)</span>', html)


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
    assert slugs(client, ADMIN, "?q=BOB") == ["ccc"]                 # creator, case-insensitive
    assert slugs(client, ADMIN, "?status=disabled") == ["aaa"]
    assert slugs(client, ADMIN, "?status=expired") == ["old"]
    assert sorted(slugs(client, ADMIN, "?status=active")) == ["bbb", "ccc"]
    assert slugs(client, ADMIN, "?owner=bob") == ["ccc"]
    assert slugs(client, ADMIN, "?q=%25") == []                       # % is literal, not a wildcard
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
    r = post(client, "/admin/links", USER, target="https://example.com/mine?a=1&b=2", slug="taken", expires_at="2031-05-06")
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    # what was typed is still in the fields
    assert 'value="https://example.com/mine?a=1&amp;b=2"' in html
    assert 'name="slug" type="text" placeholder="random" value="taken"' in html
    assert 'value="2031-05-06"' in html
    # the message is inside the "New link" card (before the "links" card), next to the offending field
    card = html[html.index("New link"):html.index("Short links are served from")]
    assert "Slug &#39;taken&#39; is already taken." in card and 'role="alert"' in card
    assert re.search(r'name="slug"[^>]*aria-invalid="true"', html) and 'name="target"' in html
    assert not re.search(r'name="target"[^>]*aria-invalid', html)
    # ... and not in the page-level flash area
    assert 'class="flash' not in html


def test_each_field_error_is_tagged_and_nothing_is_created(client):
    for data, field in [({"target": "javascript:alert(1)"}, "target"),
                        ({"target": "https://example.com", "slug": "bad slug!"}, "slug"),
                        ({"target": "https://example.com", "slug": "static"}, "slug"),
                        ({"target": "https://example.com", "expires_at": "31/12/2030"}, "expires_at"),
                        ({"target": "https://example.com", "expires_at": "2000-01-01"}, "expires_at")]:
        r = post(client, "/admin/links", USER, **data)
        html = r.get_data(as_text=True)
        assert r.status_code == 400
        assert re.search(rf'name="{field}"[^>]*aria-invalid="true"', html), data
        for key, value in data.items():                       # input is preserved
            assert f'value="{value}"' in html, (data, key)
    assert "No links yet." in client.get("/admin/", headers=USER).get_data(as_text=True)


def test_success_message_is_shown_in_the_card_and_cleared_form(client):
    r = post(client, "/admin/links", USER, target="https://example.com", slug="fine")
    assert r.status_code == 302
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    card = html[html.index("New link"):html.index("Short links are served from")]
    assert "Created" in card and 'class="form-ok"' in card and 'class="flash' not in html
    assert "form-ok" not in client.get("/admin/", headers=USER).get_data(as_text=True)  # shown once


def test_row_actions_after_failed_create_still_work(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="one")
    html = post(client, "/admin/links", USER, target="nope").get_data(as_text=True)
    assert 'name="back" value="/admin/"' in html           # not "/admin/links", which has no GET route


# ---------------------------------------------------------------- base URL, row layout
def test_base_url_is_used_for_display_and_copy(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "u.db"), "SECRET_KEY": "t", "AUTH_MODE": "proxy",
                      "BASE_URL": "https://s.example.com/"})
    c = app.test_client()
    r = post(c, "/admin/links", USER, target="https://example.com", slug="abc")
    html = c.get("/admin/", headers=USER).get_data(as_text=True)
    assert 'data-copy="https://s.example.com/abc"' in html and 'href="https://s.example.com/abc"' in html
    assert "<code>s.example.com</code>" in html and "Created https://s.example.com/abc" in html
    assert "localhost" not in html


@pytest.mark.parametrize("bad", ["s.example.com", "ftp://s.example.com", "https://s.example.com/x", "https://s.example.com/?a=1"])
def test_invalid_base_url_is_rejected(tmp_path, bad):
    with pytest.raises(RuntimeError):
        create_app({"DATABASE": str(tmp_path / "u.db"), "SECRET_KEY": "t", "AUTH_MODE": "proxy", "BASE_URL": bad})


def test_base_url_defaults_to_request_host(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="abc")
    assert 'data-copy="http://localhost/abc"' in client.get("/admin/", headers=USER).get_data(as_text=True)


def test_row_layout_copy_beside_link_delete_in_details(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    row = html[html.index('<tr class="item'):html.index('<tr class="detail"')]
    detail = html[html.index('<tr class="detail"'):html.index("</tbody>")]
    assert row.count("data-copy") == 1 and 'class="actions"' not in row and "/delete" not in row
    assert row.count('aria-label="Open short link"') == 1 and row.count('aria-label="Open target"') == 1
    assert "/delete" in detail and "Delete link" in detail
    assert 'id="links-results"' in html and 'id="filter-live"' in html


def test_cannot_create_an_already_expired_link(client):
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    r = post(client, "/admin/links", USER, target="https://example.com/x", slug="late",
             expires_at=(today - timedelta(days=1)).isoformat())
    html = r.get_data(as_text=True)
    assert r.status_code == 400 and "already passed" in html
    assert re.search(r'name="expires_at"[^>]*aria-invalid="true"', html) and 'value="https://example.com/x"' in html
    assert client.get("/late").status_code == 404
    # today still works (the link lasts until the end of that day, UTC) and so does a later day
    for slug, day in (("today", today), ("later", today + timedelta(days=30))):
        assert post(client, "/admin/links", USER, target="https://example.com/y", slug=slug,
                    expires_at=day.isoformat()).status_code == 302
        assert client.get(f"/{slug}").status_code == 302
    assert f'min="{today.isoformat()}"' in client.get("/admin/", headers=USER).get_data(as_text=True)


# ---------------------------------------------------------------- regressions: Clear button / swapped fragment
def test_swapped_fragment_contains_no_style(client):
    """The page JS swaps #links-results into the live page; a <noscript><style> in it would open every details row."""
    post(client, "/admin/links", USER, target="https://example.com", slug="abc")
    html = client.get("/admin/", headers=USER).get_data(as_text=True)
    fragment = html[html.index('id="links-results"'):html.index("</section>", html.index('id="links-results"'))]
    assert "<style" not in fragment
    assert "tr.detail[hidden]" in html and html.index("<noscript><style>") < html.index('id="links-results"')


def test_clear_button_is_disabled_not_hidden(client):
    post(client, "/admin/links", USER, target="https://example.com", slug="abc")
    plain = client.get("/admin/", headers=USER).get_data(as_text=True)
    filtered = client.get("/admin/?q=abc", headers=USER).get_data(as_text=True)
    for html, state in ((plain, "true"), (filtered, "false")):
        tag = re.search(r'<a class="btn" id="clear-filters"[^>]*>', html).group(0)
        assert f'aria-disabled="{state}"' in tag and " hidden" not in tag


def test_delete_uses_the_custom_dialog_not_window_confirm(client):
    post(client, "/admin/links", USER, target="https://example.com/t", slug="abc")
    post(client, "/admin/rules", ADMIN, pattern="gh/*", target="https://github.com/{1}")
    links = client.get("/admin/", headers=USER).get_data(as_text=True)
    rules = client.get("/admin/rules", headers=ADMIN).get_data(as_text=True)
    for html in (links, rules):
        assert "confirm(" not in html and "onsubmit" not in html
        assert '<dialog id="confirm"' in html and html.index('id="confirm-yes"') < html.index('value="no"')  # accept first (left)
    assert 'data-confirm-name="/abc"' in links and 'data-confirm-name="gh/*"' in rules
