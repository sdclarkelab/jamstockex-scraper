import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
JSE_URL = re.compile(r"https?://[^\s\"'<>]*jamstockex\.com", re.IGNORECASE)


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
