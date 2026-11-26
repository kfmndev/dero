# Contributing

## Setup

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/pytest
```

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<optional scope>): <short summary in imperative mood>
```

| Type | Use for |
| --- | --- |
| `feat` | a new feature |
| `fix` | a bug fix |
| `docs` | documentation only |
| `test` | adding or fixing tests |
| `refactor` | code change that neither fixes a bug nor adds a feature |
| `chore` | maintenance, dependencies, tooling, CI |

Breaking changes are marked with `!` after the type (`feat!: ...`) or a `BREAKING CHANGE:` footer.

Examples: `feat(rules): add regex match type`, `fix: reject javascript: targets`.

## Code style

Python is formatted and checked with [Ruff](https://docs.astral.sh/ruff/) at 120 columns (settings in
`pyproject.toml`; it formats like black and also sorts imports). Before committing:

```bash
pip install -r requirements-dev.txt
ruff format dero tests
ruff check dero tests
pytest
```

Blank lines structure a function: one before an `if`, `for`, `try` or `with` that follows other statements, and
before a closing `return` in a longer block. Long functions are split instead of padded.

## Code layout

- `dero/__init__.py` – the app factory only. Around it: `forms.py` (reading the New link and edit forms: slugs,
  expiry), `display.py` (how slugs and short links are drawn: the template filters), `urls.py` (the public base
  address), `query.py` (the search language), `resolve.py` (slugs, URLs and rules), `auth.py`, `db.py`, `passwd.py`
  (users and storage).
- `dero/admin/` – the admin UI as a blueprint: `links.py` (list, create, edit, delete), `live.py` (the live-visits
  stream), `rules.py` (pattern rules and the fallback), `listing.py` (building the links page), `helpers.py`.
- `dero/templates/` – Jinja pages. Lines stay under about 120 characters: attributes wrap one per line, and
  repeated markup lives in macros (`_macros.html`). Where a template breaks a line between inline elements it uses
  `{{-` / `{%-` so no stray space appears in the page.
- `dero/static/style.css` – one stylesheet in commented sections (see the note at its top: the order of rules matters).
- `dero/static/js/` – the page's scripts. They are plain scripts that share one scope and are listed in
  `templates/base.html`, **in load order** (later files use the functions of earlier ones):

  | file | what it does |
  | --- | --- |
  | `core.js` | copy buttons, opening a link's details, local times, swapping a region of the page |
  | `checks.js` | the checks shared by the New link form and the edit form, messages, URL warnings |
  | `new-link.js` | the New link form: slug source, Generate, expiry switch |
  | `search-language.js` | parser, renderer and editing helpers of the search language (mirrors `query.py`) |
  | `filters.js` | the search bar, the dropdowns that edit the query, columns, Reset |
  | `live.js` | Live visits (server-sent events); uses what `filters.js` hands over in `window.deroFilters` |
  | `slugs.js` | slug colouring and the coloured slug editor |
  | `settings.js` | the settings dialog |
  | `confirm.js` | the delete confirmation dialog |
  | `edit.js` | editing a link in its details |
  | `actions.js` | sending forms without reloading the page |
  | `dropdowns.js` | upgrades every `<select>` to the shared dropdown (runs last) |

  A function that other scripts call while the page loads must live in a file that loads earlier (`refreshSelect`
  is in `core.js` for that reason).

## Pull requests

Work on a branch, keep the tests passing (`pytest`), and describe what changed and why.
