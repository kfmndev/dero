import re

import pytest

from dero import create_app

USER = {"Remote-User": "alice", "Remote-Groups": "dero-users"}
USER2 = {"Remote-User": "bob", "Remote-Groups": "dero-users"}
ADMIN = {"Remote-User": "root", "Remote-Groups": "dero-admins,other"}


@pytest.fixture
def app(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "t.db"), "SECRET_KEY": "test", "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


def token(client, headers):
    html = client.get("/_/", headers=headers).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def post(client, path, headers, **data):
    return client.post(path, headers=headers, data={"csrf": token(client, headers), **data})


def visits(client, headers):
    html = client.get("/_/", headers=headers).get_data(as_text=True)
    return html


def test_access_control(client):
    assert client.get("/_/").status_code == 403
    assert client.get("/_/", headers={"Remote-User": "eve"}).status_code == 403
    assert client.get("/_/", headers={"Remote-User": "eve", "Remote-Groups": "nope"}).status_code == 403
    assert client.get("/_/", headers=USER).status_code == 200


def test_proxy_secret(app):
    app.config["PROXY_SECRET"] = "s3"
    c = app.test_client()
    assert c.get("/_/", headers=USER).status_code == 403
    assert c.get("/_/", headers={**USER, "X-Proxy-Secret": "s3"}).status_code == 200


def test_csrf_required(client):
    r = client.post("/_/links", headers=USER, data={"target": "https://example.com"})
    assert r.status_code == 400


def test_create_and_redirect_counts_visits(client, app):
    post(client, "/_/links", USER, target="https://example.com/a", slug="abc")
    r = client.get("/abc")
    assert r.status_code == 302 and r.headers["Location"] == "https://example.com/a"
    assert r.headers["Cache-Control"] == "no-store"
    client.get("/abc"); client.get("/abc/")
    with app.app_context():
        from dero.db import get_db
        row = get_db().execute("SELECT visits, created_by FROM links WHERE slug='abc'").fetchone()
        assert (row["visits"], row["created_by"]) == (3, "alice")


def test_random_slug_and_duplicate(client):
    post(client, "/_/links", USER, target="https://example.com")
    post(client, "/_/links", USER, target="https://example.com/x", slug="dup")
    r = post(client, "/_/links", USER, target="https://example.com/y", slug="dup")
    assert client.get("/dup").headers["Location"] == "https://example.com/x"
    assert "already taken" in client.get("/_/", headers=USER).get_data(as_text=True) or r.status_code == 302


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://x.y/z", "notaurl", "https://"])
def test_rejects_bad_urls(client, bad):
    post(client, "/_/links", USER, target=bad, slug="bad")
    assert client.get("/bad").status_code == 404


def test_disable_and_expiry(client):
    post(client, "/_/links", USER, target="https://example.com", slug="gone", expires_at="2000-01-01")
    assert client.get("/gone").status_code == 404
    post(client, "/_/links", USER, target="https://example.com", slug="off")
    assert client.get("/off").status_code == 302
    post(client, "/_/links/2/toggle", USER)
    assert client.get("/off").status_code == 404


def test_ownership(client):
    post(client, "/_/links", USER, target="https://example.com", slug="mine")
    assert post(client, "/_/links/1/delete", USER2).status_code == 404
    assert client.get("/mine").status_code == 302
    assert post(client, "/_/links/1/delete", ADMIN).status_code == 302
    assert client.get("/mine").status_code == 404


def test_rules_admin_only(client):
    assert client.get("/_/rules", headers=USER).status_code == 403
    assert post(client, "/_/rules", USER, pattern="x", target="https://e.com").status_code == 403


def test_glob_rules_priority_and_fallback(client):
    post(client, "/_/rules", ADMIN, pattern="gh/*", target="https://github.com/{1}", priority="50")
    post(client, "/_/rules", ADMIN, pattern="gh/**", target="https://example.com/all/{1}", priority="10")
    assert client.get("/gh/foo").headers["Location"] == "https://example.com/all/foo"  # lower number wins
    post(client, "/_/rules/1/priority", ADMIN, priority="1")
    assert client.get("/gh/foo").headers["Location"] == "https://github.com/foo"
    assert client.get("/gh/foo/bar").headers["Location"] == "https://example.com/all/foo/bar"
    assert client.get("/nothing").status_code == 404
    post(client, "/_/settings/fallback", ADMIN, fallback_url="https://example.com/rick")
    assert client.get("/nothing").headers["Location"] == "https://example.com/rick"
    assert client.get("/").headers["Location"] == "https://example.com/rick"


def test_exact_link_beats_rule(client):
    post(client, "/_/rules", ADMIN, pattern="**", target="https://example.com/{1}")
    post(client, "/_/links", USER, target="https://real.example", slug="abc")
    assert client.get("/abc").headers["Location"] == "https://real.example"


def test_regex_rule_and_timeout(client):
    post(client, "/_/rules", ADMIN, pattern=r"v(\d+)", match_type="regex", target="https://e.com/ver/{1}")
    assert client.get("/v42").headers["Location"] == "https://e.com/ver/42"
    post(client, "/_/rules", ADMIN, pattern=r"(a+)+$", match_type="regex", target="https://e.com/evil", priority="1")
    import time
    t = time.time()
    assert client.get("/" + "a" * 40 + "!").status_code == 404  # catastrophic pattern is cut off
    assert time.time() - t < 2


def test_rule_validation(client):
    post(client, "/_/rules", ADMIN, pattern="a/*", target="https://e.com/{2}")       # placeholder > groups
    post(client, "/_/rules", ADMIN, pattern="(", match_type="regex", target="https://e.com")
    post(client, "/_/rules", ADMIN, pattern="b", target="javascript:alert(1)")
    assert client.get("/a/x").status_code == 404 and client.get("/b").status_code == 404


def test_target_placeholder_is_escaped(client):
    post(client, "/_/rules", ADMIN, pattern="q/*", target="https://e.com/s?q={1}")
    assert client.get("/q/a b").headers["Location"] == "https://e.com/s?q=a%20b"
