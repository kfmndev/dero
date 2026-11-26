"""Version and build information shown in the page footer.

The commit is taken from the DERO_COMMIT environment variable if set (for
builds without a .git folder, e.g. a Docker image built with
--build-arg DERO_COMMIT=$(git rev-parse HEAD)), otherwise from git.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

VERSION = "0.1.0"
REPO_URL = "https://github.com/kfmndev/dero"

ROOT = Path(__file__).resolve().parent
_HASH = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class BuildInfo:
    version: str
    repo_url: str
    commit: str | None  # full hash, if known
    dirty: bool = False  # running from a checkout with uncommitted changes

    @property
    def short_commit(self) -> str | None:
        return self.commit[:7] if self.commit else None

    @property
    def commit_url(self) -> str | None:
        return f"{self.repo_url}/commit/{self.commit}" if self.commit else None


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        return None

    return result.stdout.strip()


@lru_cache(maxsize=1)
def build_info() -> BuildInfo:
    repo_url = os.environ.get("DERO_REPO_URL", REPO_URL).rstrip("/")
    commit = os.environ.get("DERO_COMMIT", "").strip().lower()

    if _HASH.match(commit):
        return BuildInfo(VERSION, repo_url, commit)

    commit = (_git("rev-parse", "HEAD") or "").lower()

    if not _HASH.match(commit):
        return BuildInfo(VERSION, repo_url, None)
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))

    return BuildInfo(VERSION, repo_url, commit, dirty)
