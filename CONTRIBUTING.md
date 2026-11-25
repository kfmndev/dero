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

## Pull requests

Work on a branch, keep the tests passing (`pytest`), and describe what changed and why.
