# Contributing

## Setup

```sh
uv sync            # creates .venv with the exact versions in uv.lock: the app, pytest, Ruff and Pyrefly
uv run pytest
```

[uv](https://docs.astral.sh/uv/) manages the dependencies. They are declared in `pyproject.toml` and pinned in
`uv.lock`; change them with `uv add <package>` / `uv add --dev <package>` or `uv lock --upgrade`, and commit both files.

## Commit messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Every commit has a
type and a scope:

```
<type>(<scope>): <short summary in imperative mood>
```

| Type | Use for |
| --- | --- |
| `feat` | a new feature or a visible change of behaviour or design |
| `fix` | a bug fix |
| `docs` | documentation, including docstrings |
| `test` | adding or fixing tests |
| `refactor` | code change that neither fixes a bug nor adds a feature |
| `style` | formatting only (whitespace, line breaks, import order): the code means the same afterwards |
| `perf` | a change that makes something faster |
| `build` | the Docker image, dependencies |
| `ci` | the GitHub Actions workflow |
| `chore` | other maintenance and tooling |
| `revert` | undoing an earlier commit |

A change of how the app looks is a `feat` or a `fix`, not a `style`: in this convention `style` is about the
formatting of the code.

Scopes name the area: `ui` (layout, spacing, components), `search` (the search language and bar), `links`
(the table and the details), `slugs`, `live`, `rules`, `auth`, `forms`, `deploy` (Docker, compose, Caddy),
`python`, `cli` (the command line tools and the log), `types`, `static` (the scripts and the stylesheet as files), `tooling`, `ci`, `docs`, `tests`.
Add a new one when none fits.

Breaking changes are marked with `!` after the scope (`feat(rules)!: ...`) or a `BREAKING CHANGE:` footer.

Examples: `feat(rules): add regex match type`, `fix(forms): reject javascript: targets`,
`style(python): wrap long lines`.

## Code style

Everything is formatted to 120 columns. The setting lives in `pyproject.toml` (Ruff) and `biome.jsonc` (Biome);
the stylesheet, scripts and templates follow it too.

**Python** is formatted and checked with [Ruff](https://docs.astral.sh/ruff/) (it formats like black, sorts
imports and replaces flake8) and type-checked with [Pyrefly](https://pyrefly.org/):

```bash
ruff format dero tests
ruff check dero tests
pyrefly check
pytest
```

Every function in `dero/` has a docstring and type hints (tests are exempt for now). Ruff checks the docstrings of
public names; `tests/test_style.py` also covers the private helpers and the hints.

Blank lines structure a function: one before an `if`, `for`, `try` or `with` that follows other statements, and
before a closing `return` in a longer block. Long functions are split instead of padded.

**Scripts and stylesheet** (`dero/static/js`, `dero/static/style.css`) are formatted and linted with
[Biome](https://biomejs.dev/). Install it from npm (`npm install --global @biomejs/biome`) or as a standalone
binary, then run `biome ci` to check or `biome check --write` to fix.

**Templates** (`dero/templates`) are Jinja, which the formatters above would damage, so they are formatted by
hand: attributes wrap one per line, repeated markup lives in macros (`_macros.html`), and where a line breaks
between inline elements the template uses `{{-` or `{%-` so no stray space appears in the page.

**CI**: `.github/workflows/ci.yml` runs the Ruff, Pyrefly and Biome checks and the tests on every push to `main`
and on pull requests; a newer push to the same branch cancels the run it makes obsolete (the Docker workflow too).
The actions in it are pinned to commit SHAs; Dependabot (`.github/dependabot.yml`) opens a pull
request weekly when one has a newer release. It also watches the dependencies (`uv.lock`), the base
images in the Dockerfile and the git-cliff version in `.github/requirements-release.txt`.

**Docker image**: `.github/workflows/docker.yml` builds the image on every pull request (nothing is pushed) and publishes
it to `ghcr.io/kfmndev/dero` from `main` (`:edge`) and from release tags (`v1.2.3` becomes `:1.2.3`, `:1.2`, `:latest`).
The compose files for running it are in `deploy/`.

**Releases**: raise `version` in `pyproject.toml` (the footer reads it from there), commit, then push a tag
`vX.Y.Z` on that commit. `.github/workflows/release.yml` fails if the tag and that version differ, and otherwise creates
the GitHub release with notes grouped by commit type (`cliff.toml`; preview them with `git cliff --unreleased`). A tag
with a hyphen (`v0.2.0-rc1`) is marked as a pre-release.

## Code layout

- `dero/__init__.py` – the app factory only. Around it: `forms.py` (reading the New link and edit forms: slugs,
  expiry), `display.py` (how slugs and short links are drawn: the template filters), `urls.py` (the public base
  address), `query.py` (the search language), `resolve.py` (slugs, URLs and rules), `types.py` (what a view returns),
  `auth.py`, `db.py`, `passwd.py` (users and storage).
- `dero/admin/` – the admin UI as a blueprint: `links.py` (list, create, edit, delete), `live.py` (the live-visits
  stream), `rules.py` (pattern rules and the fallback), `listing.py` (building the links page), `helpers.py`.
- `dero/templates/` – Jinja pages, formatted by hand (see Code style).
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
- `tools/make_logo.py` – draws the README logos in `assets/` from the header font; run `uv run tools/make_logo.py`
  (it declares its own dependencies) after changing the header font or the colours.

## Pull requests

Work on a branch, keep the tests passing (`pytest`), and describe what changed and why.
