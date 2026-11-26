<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
  <img src="assets/logo-light.svg" alt="dero" height="100">
</picture>

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
cp .env.example .env                                  # set SECRET_KEY (openssl rand -hex 32)
cp deploy/docker-compose.example.yml docker-compose.yml
docker compose up -d                                  # pulls ghcr.io/kfmndev/dero

# create the first admin (prompts for a password, writes /data/users.txt)
docker compose run --rm dero python -m dero.passwd --file /data/users.txt alice --role admin
```

To build the image yourself instead, use [`deploy/docker-compose.build.example.yml`](deploy/docker-compose.build.example.yml) (`docker compose -f deploy/docker-compose.build.example.yml --env-file .env up -d --build`). CI publishes `main` as `:edge` and each release `v1.2.3` as `:1.2.3`, `:1.2` and `:latest`.

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
| Status / Created by dropdowns | tick all = no filter; untick all = nothing is shown (`status!=active,disabled,expired`) |
| `created_by=julian` · `slug=abc` · `target=github` | creator (exact), parts of slug or target |
| `slug=abc*` · `target=*.pdf` · `created_by=ann*` | a `*` is any text, and then the whole value must match: `abc*` starts with, `*.pdf` ends with, `a*c` both. Upper and lower case never matter |
| `slug==abc` | exactly this: no parts and no wildcards (a `*` is just a `*`) |
| *×* behind a term | removes that term (and its *and*/*or*); the × behind an operator (`and`, `or`, `&&`, `||`) removes just the operator |
| `( … )` | group; typing or pasting a parenthesis against a term adds a space on each side |
| `created>-7d` · `expires<30d` · `created=today` | dates relative to today (UTC): `today`, `yesterday`, `tomorrow`, or a number of days, weeks, months or years (`d` `w` `m` `y`); `-` for the past, nothing for the future: `-7d`, `2w`, `-1y`. `expires<30d` also matches links that have expired already, so use `expires>=today expires<30d` for "expiring soon" |
| `visits>100` · `visits=0` · `visits!=5` | the visit counter: a whole number, with `<` `<=` `>` `>=` `=` `!=` |
| `created=2026-11` · `expires<2027-01-01` · `created>=2026` | creation or expiry date: a year, month or day (UTC); compare with `<` `<=` `>` `>=` written directly after the key (not after the `=`). A link without an expiry matches no date |
| `expires` · `!expires` · `expires=never` | `expires` alone is short for `expires!=never`: links that expire. `!expires` or `expires=never` (also `none`): links that never do |
| `sort_by=visits` · `sort_by=-visits` | sort by `created`, `visits`, `slug`, `target`, `created_by` (or `creator`) or `expires`; a minus reverses the usual order |
| `!status=expired` · `status!=expired` | negation |
| `a and b` · `a && b` · `a or b` · `a \|\| b` · `( )` | explicit operators and grouping (*and* binds tighter than *or*) |
| `created_by="Anna Maria"` | quotes for values with spaces |

The key names are the dropdowns' names in snake case: `status`, `created_by`, `sort_by`. The older spellings `creator`, `owner`, `by`, `sortby`, `sort` and `order` still work.

Unknown keys are plain text, so a pasted URL just searches for that text. A known key with an operator it does not have (`slug>abc`, `status<x`) matches nothing, is underlined in the search bar and reported above the table. Terms, groups and negations are shown as chips in the search bar, and invalid values are underlined. People only ever see their own links, whatever the query says.

**Columns:** the *Columns* dropdown shows or hides any of Slug, Target, Created by, Created, Expires and Visits (the default is Slug, Target and Visits). The choice is remembered in a cookie, so the server draws exactly those columns.

## 🔤 Slugs and warnings

- **Slug source:** one dropdown in the New link form: *Random · default* (letters and digits without look-alikes: `abcdefghjkmnpqrstuvwxyz23456789`), *Random · letters only*, *Random · own characters* or *Custom slug*. Random slugs have a length of 3 to 32 (default 5). In your own characters a repeated character is more likely (`aaab` is 75 % `a`). The choice is remembered in the browser.
- **Slugs** may use anything that is safe in a URL: letters, digits and `- _ . ~`, up to 64 characters (so `v1.2` and `---` are fine, `...` is not).
- **Generate first:** the *Generate* button draws a slug of the selected type into the Custom slug field, so you can look at it, edit it and then create the link (from Custom it uses the random type chosen last).
- **Settings:** click your user name (top right) to open the settings dialog. *Colour slugs* turns the digit/symbol colouring of slugs on or off (table, created message, delete dialog). It is stored in the `dero_hl` cookie.
- **Messages sit where they belong:** errors and warnings under the row of the field in the New link form, update results in the details of the link. An update reads like `abc updated · new target https://…` (the target is cut when long).
- **Live visits:** an option in the settings dialog. While it is on, the page keeps a server-sent-events stream open (`/admin/links/visits/stream`); the server checks the visit counters about once a second and pushes a message when one goes up. The row of that slug lights up and its count changes in place. Only the counter is read, so no visit is recorded (no times, no IPs). Each open stream holds one worker thread, so the Docker image runs gunicorn with threads (`-k gthread --threads 16`); hidden tabs close their stream after 30 seconds. Caddy streams `text/event-stream` as it is; behind nginx the `X-Accel-Buffering: no` header the app sends turns buffering off.
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
uv sync          # exact versions from uv.lock, dev tools included
uv run pytest
```

## 📖 Project guidelines

- [Contributing](CONTRIBUTING.md): setup, [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and PR flow

## 📄 License

[AGPL-3.0](LICENSE)
