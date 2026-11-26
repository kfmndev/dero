"""Rules about the code that no formatter checks: every function in dero/ has a docstring and type hints."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "dero"
FILES = sorted(APP.rglob("*.py"))


def problems(path):
    """The functions of a file that lack a docstring, a parameter hint or a return hint."""
    found = []

    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        args = [
            a for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs if a.arg not in ("self", "cls")
        ]
        args += [a for a in (node.args.vararg, node.args.kwarg) if a]

        if not ast.get_docstring(node):
            found.append(f"{path.name}:{node.lineno} {node.name}: no docstring")

        if node.returns is None or not all(a.annotation for a in args):
            found.append(f"{path.name}:{node.lineno} {node.name}: missing type hints")

    return found


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(APP)))
def test_every_function_has_a_docstring_and_type_hints(path):
    """One check per file, so a failure names the file and the functions."""
    assert problems(path) == []


def test_the_check_finds_the_files():
    """Guard against the glob matching nothing, which would make every check above pass for no reason."""
    assert len(FILES) >= 15
