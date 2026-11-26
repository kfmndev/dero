<div align="center">

# dero

**Tiny, privacy-first URL shortener. Counts visits, nothing else.**

[![License](https://img.shields.io/github/license/kfmndev/dero?style=flat-square)](https://github.com/kfmndev/dero/blob/main/LICENSE) [![Python](https://img.shields.io/badge/python-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org) [![Flask](https://img.shields.io/badge/flask-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com) [![Tag](https://img.shields.io/github/v/tag/kfmndev/dero?style=flat-square)](https://github.com/kfmndev/dero/tags)
</div>

## 🎯 TL;DR

- A slug (`/<slug>`) redirects to a target URL; every redirect increments a **visit counter**
- Stored per link: slug, target, **creator**, creation date, optional expiry, visit count. **No IPs, referrers or user agents**
- Lookup order: **exact link** → **pattern rule** (lowest priority number first) → **fallback URL** → `404`
- Example pattern rule: `gh/*` → `https://github.com/{1}`
- Small admin UI in the style of [podutils](https://github.com/kfmndev/podutils) with a blue accent: compact links table (click a row for creator, dates, the full target and delete), live sorting, search and filters, enable/disable sliders, light and dark mode (follows the browser, toggle overrides), no external requests, fonts bundled
- Admin UI at `/admin`, protected by **HTTP Basic auth** (users file with hashed passwords). SSO via a reverse proxy such as [Authelia](https://www.authelia.com) is available as `AUTH_MODE=proxy`

> [!IMPORTANT]
> Basic auth sends the password with every request: **serve dero over HTTPS only**. dero has no login throttling, so use strong passwords and, if exposed to the internet, rate-limit `/admin` at your reverse proxy.

> [!NOTE]
> Redirects are `302` and sent with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`, so counting and disabling links keep working. Only `http://` and `https://` targets are accepted.

## 🚀 Quick start

Requirements: Docker and a reverse proxy with TLS (e.g. Caddy) in front of dero.

```sh
cp .env.example .env       # set SECRET_KEY (openssl rand -hex 32)
docker compose up -d --build   # optional: DERO_COMMIT=$(git rev-parse HEAD) shows the commit in the footer

# create the first admin (prompts for a password, writes /data/users.txt)
docker compose run --rm dero python -m dero.passwd --file /data/users.txt alice --role admin
```

The users file is re-read when it changes, so no restart is needed. Each line is `username:role:hash` with role `admin` (everything, plus rules and fallback) or `user` (own links only); a later line overrides an earlier one for the same user.

```caddyfile
s.example.com {
	reverse_proxy dero:8000
}
```

Then open `https://s.example.com/admin/`. Slugs (`/<slug>`) stay public.

### No authentication (`AUTH_MODE=none`)

Everyone who can reach `/admin` is an admin, recorded as `NONE_USER`. Only use this when something else already controls access, for example a private network, a VPN, or a reverse proxy doing its own authentication. dero logs a warning at startup in this mode.

### SSO instead (`AUTH_MODE=proxy`)

dero then trusts the identity headers (`Remote-User`, `Remote-Groups`) set by your proxy and does no password checking itself, so it **must only be reachable through that proxy** (don't publish its port; `PROXY_SECRET` adds a second lock). Examples for Caddy + Authelia are in [`deploy/`](deploy). Members of the group `dero-users` manage their own links, `dero-admins` everything.

## 🔎 Search

The search box is a small query language; the dropdowns (status, created by, sort) show it and edit it, and the other way round. Everything updates as you type, and the query lives in the URL (`?q=…`).

| Query | Meaning |
| --- | --- |
| `github "exact phrase"` | free text: searches slug, target and creator; terms are joined with *and* |
| `status=expired,disabled` | status (`active`, `disabled`, `expired`); a comma means *or* |
| `creator=julian` · `slug=abc` · `target=github` | creator (exact), parts of slug or target |
| *×* behind a term | removes that term (and its *and*/*or*) |
| `sortby=visits` · `sortby=-visits` | sort by `created`, `visits`, `slug`, `target`, `creator` or `expires`; a minus reverses the usual order |
| `!status=expired` · `status!=expired` | negation |
| `a and b` · `a && b` · `a or b` · `a \|\| b` · `( )` | explicit operators and grouping (*and* binds tighter than *or*) |
| `creator="Anna Maria"` | quotes for values with spaces |

Unknown keys are plain text, so a pasted URL just searches for that text. Terms, groups and negations are shown as chips in the search bar, and invalid values are underlined. People only ever see their own links, whatever the query says.

**Columns:** the *Columns* dropdown shows or hides any of Slug, Target, Created by, Created, Expires and Visits (the default is Slug, Target and Visits). The choice is remembered in a cookie, so the server draws exactly those columns.

## 🔤 Slugs and warnings

- **Slug source:** one dropdown in the New link form: *Random · default* (letters and digits without look-alikes: `abcdefghjkmnpqrstuvwxyz23456789`), *Random · letters only*, *Random · own characters* or *Custom slug*. Random slugs have a length of 3 to 32 (default 5). In your own characters a repeated character is more likely (`aaab` is 75 % `a`). The choice is remembered in the browser.
- **Slugs** may use anything that is safe in a URL: letters, digits and `- _ . ~`, up to 64 characters (so `v1.2` and `---` are fine, `...` is not).
- **Generate first:** the *Generate* button draws a slug of the selected type into the Custom slug field, so you can look at it, edit it and then create the link (from Custom it uses the random type chosen last).
- **Settings:** click your user name (top right) to open the settings dialog. *Colour slugs* turns the digit/symbol colouring of slugs on or off (table, created message, delete dialog). It is stored in the `dero_hl` cookie.
- **Messages sit where they belong:** errors and warnings under the row of the field in the New link form, update results in the details of the link. An update reads like `abc updated · new target https://…` (the target is cut when long).
- **Expired links** are marked with a small clock after the link icons.
- **Readable slugs:** in the table, digits are blue and symbols red (like Bitwarden shows passwords), letters stay plain.
- **Warnings, not walls:** an unusual address (http, no domain ending, IP address, port, login, spaces), an address that already has a slug, or an expiry date in the past gets a short warning; press Create (or Update) again to go ahead. Clearly invalid input is still refused.

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
| `AUTH_MODE` | `basic` | `basic` (users file), `proxy` (SSO headers from the reverse proxy) or `none` (no authentication) |
| `NONE_USER` | `admin` | `none` mode: the username recorded as creator of new links |
| `USERS_FILE` | `users.txt` (`/data/users.txt` in Docker) | Basic-auth users, one `username:role:hash` per line; create with `python -m dero.passwd` |
| `SECRET_KEY` | random per start | Signs form tokens (CSRF). Set it, or forms break after restarts |
| `PROXY_SECRET` | *(empty)* | `proxy` mode only: if set, requests must carry a matching `X-Proxy-Secret` header |
| `BASE_URL` | request host | Public address of the slugs, e.g. `https://s.example.com`. Used to display and copy links; set it when dero runs behind a proxy under a different name |
| `FALLBACK_URL` | *(empty)* | Initial fallback target; later editable in the UI. Empty means `404` |
| `USER_GROUP` / `ADMIN_GROUP` | `dero-users` / `dero-admins` | `proxy` mode: groups allowed to use / administer dero |
| `USER_HEADER` / `GROUPS_HEADER` | `Remote-User` / `Remote-Groups` | `proxy` mode: identity headers set by the proxy |
| `ADMIN_PATH` | `/admin` | URL prefix of the admin UI (must match the Caddy/Authelia rules). A slug with the same name is reserved |
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
