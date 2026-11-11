"""Build jamstockex.pyz with the standard library's zipapp.

Usage: python .github/build_pyz.py dist/jamstockex.pyz

The archive holds the jamstockex package (with openapi.json and static/) and a
__main__.py that passes main()'s return value to sys.exit, so exit codes survive.
"""

import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = "import sys\n\nfrom jamstockex.__main__ import main\n\nsys.exit(main())\n"


def build(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "app"
        shutil.copytree(ROOT / "jamstockex", staging / "jamstockex",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (staging / "__main__.py").write_text(MAIN, encoding="utf-8")
        zipapp.create_archive(staging, target, interpreter="/usr/bin/env python3", compressed=True)
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python .github/build_pyz.py <output.pyz>")
    print(build(Path(sys.argv[1])))
