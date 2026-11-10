"""Test doubles shared by the refresh, CLI and server tests."""

from jamstockex.fetch import BlockedError
from tests.helpers import fixture_html


class FakeFetcher:
    """Serves pages by path prefix; mimics Fetcher's block behaviour and request count."""

    def __init__(self, pages):
        self.pages = pages
        self.paths = []
        self.request_count = 0
        self.blocked = False

    def get(self, path):
        if self.blocked:
            raise BlockedError(f"Not requesting {path}: an earlier request was blocked")
        self.paths.append(path)
        self.request_count += 1
        for prefix, page in self.pages.items():
            if path.startswith(prefix):
                if isinstance(page, BlockedError):
                    self.blocked = True
                if isinstance(page, Exception):
                    raise page
                return page
        raise AssertionError(f"unexpected request: {path}")


def pages(overrides=None):
    """The synthetic site: Main Market has two instruments, the other markets are empty."""
    empty = fixture_html("listed-companies-empty.html")
    result = {
        "/trading/trade-quotes/": fixture_html("trade-quotes.html"),
        "/listings/listed-companies/?market=31": fixture_html("listed-companies.html"),
        "/listings/listed-companies/?market=22": empty,
        "/listings/listed-companies/?market=51": empty,
        "/listings/listed-companies/?market=49": empty,
        "/trading/corporate-actions/": fixture_html("corporate-actions.html"),
    }
    result.update(overrides or {})
    return result
