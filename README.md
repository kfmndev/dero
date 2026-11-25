<div align="center">

# dero

**Tiny, privacy-first URL shortener. Counts visits, nothing else.**

[![License](https://img.shields.io/github/license/kfmndev/dero?style=flat-square)](https://github.com/kfmndev/dero/blob/main/LICENSE) [![Python](https://img.shields.io/badge/python-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org) [![Flask](https://img.shields.io/badge/flask-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com) [![Tag](https://img.shields.io/github/v/tag/kfmndev/dero?style=flat-square)](https://github.com/kfmndev/dero/tags)
</div>

## 🎯 TL;DR

- Short links `/<slug>` redirect to a target URL; every redirect increments a **visit counter**
- Stored per link: slug, target, **creator**, creation date, optional expiry, visit count. **No IPs, referrers or user agents**
- Lookup order: **exact link** → **pattern rule** (lowest priority number first) → **fallback URL** → `404`
- Example pattern rule: `gh/*` → `https://github.com/{1}`
- No passwords: sign-in is delegated to a reverse proxy with [Authelia](https://www.authelia.com) (or any forward-auth identity provider)

> [!IMPORTANT]
> dero **trusts the identity headers** (`Remote-User`, `Remote-Groups`) sent by the reverse proxy. It must only be reachable through that proxy: do not publish its port. `PROXY_SECRET` adds a second lock.

> [!NOTE]
> Redirects are `302` and sent with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`, so counting and disabling links keep working. Only `http://` and `https://` targets are accepted.

## 🚀 Quick start

Requirements: Docker, and a reverse proxy (e.g. Caddy) in front of an Authelia instance.

```sh
cp .env.example .env       # set SECRET_KEY and PROXY_SECRET (openssl rand -hex 32)
docker compose up -d --build
```

Route only the admin UI through Authelia and keep short links public (full examples in [`deploy/`](deploy)):

```caddyfile
s.example.com {
	@admin path /_ /_/*
	handle @admin {
		forward_auth authelia:9091 {
			uri /api/authz/forward-auth
			copy_headers Remote-User Remote-Groups
		}
		reverse_proxy dero:8000 { header_up X-Proxy-Secret {$PROXY_SECRET} }
	}
	handle {
		reverse_proxy dero:8000
	}
}
```

Add users to the groups `dero-users` (manage own links) and `dero-admins` (everything, plus rules and fallback) in Authelia, then open `https://s.example.com/_/`.

## 🧩 Pattern rules

Admin-only. Rules apply after exact links and are tried by ascending priority.

| Type | Syntax | Example | Result for `/gh/octocat` |
| --- | --- | --- | --- |
| glob (default) | `*` any text except `/`, `**` any text, `?` one character | `gh/*` → `https://github.com/{1}` | `https://github.com/octocat` |
| regex | captured groups as `{1}`, `{2}`, … (50 ms match timeout) | `v(\d+)` → `https://example.com/ver/{1}` | n/a |

Captured text is URL-encoded before it is placed into the target.

## ⚙️ Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `SECRET_KEY` | random per start | Signs form tokens (CSRF). Set it, or forms break after restarts |
| `PROXY_SECRET` | *(empty)* | If set, requests must carry a matching `X-Proxy-Secret` header |
| `FALLBACK_URL` | *(empty)* | Initial fallback target; later editable in the UI. Empty means `404` |
| `USER_GROUP` / `ADMIN_GROUP` | `dero-users` / `dero-admins` | Groups allowed to use / administer dero |
| `USER_HEADER` / `GROUPS_HEADER` | `Remote-User` / `Remote-Groups` | Identity headers set by the proxy |
| `DATABASE` | `dero.db` (`/data/dero.db` in Docker) | SQLite file |

## 🛠️ Development

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/pytest
```

## 📖 Project guidelines

- [Contributing](CONTRIBUTING.md): setup, [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and PR flow

## 📄 License

[AGPL-3.0](LICENSE)
