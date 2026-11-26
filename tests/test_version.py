import tomllib
from pathlib import Path

from dero.version import VERSION


def test_the_version_comes_from_pyproject():
    project = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())

    assert VERSION == project["project"]["version"]
    assert VERSION != "unknown"
