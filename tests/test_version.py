import tomllib
from pathlib import Path

from dero.version import VERSION


def test_pyproject_version_matches_the_footer_version():
    project = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())

    assert project["project"]["version"] == VERSION
