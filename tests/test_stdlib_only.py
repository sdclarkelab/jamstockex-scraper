"""jamstockex/ must import nothing outside the standard library (spec §3.1)."""

import ast
import sys

from tests.helpers import ROOT


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def test_package_imports_only_the_standard_library():
    files = sorted((ROOT / "jamstockex").rglob("*.py"))
    assert files, "no package files found"
    outside = {
        f"{path.relative_to(ROOT)}: {name}"
        for path in files
        for name in imported_modules(path)
        if name != "jamstockex" and name not in sys.stdlib_module_names and name != "__future__"
    }
    assert outside == set()
