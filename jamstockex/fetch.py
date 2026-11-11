"""Honest HTTP client for the JSE website, on urllib.request.

One honest User-Agent, a timeout, a random pause between requests, and retries
only for transient failures. A block (403/429 or a CloudFront "Request blocked"
page) is never retried or worked around, and after one this Fetcher refuses to
send any more requests (JSE Terms & Conditions §8.2).

Error messages name the request path, never the host or URL: they are shown in
/v2/status, which must not link to the JSE site.
"""

from __future__ import annotations

import codecs
import http.client
import logging
import random
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from jamstockex.config import SourceConfig

log = logging.getLogger(__name__)

BLOCK_STATUSES = frozenset({403, 429})


class FetchError(Exception):
    """A page could not be fetched (after retries, or a status that isn't retried)."""


class BlockedError(FetchError):
    """The site is blocking this client. Never retried or worked around."""


def is_block_page(text: str) -> bool:
    return "Request blocked" in text and "cloudfront" in text.lower()


def _decode(body: bytes, charset: str | None) -> str:
    try:
        codecs.lookup(charset or "utf-8")
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:  # unknown, or a non-text codec such as base64 or rot13
        return body.decode("utf-8", errors="replace")


def _problem(exc: BaseException) -> str:
    """Exception class names only: exception text can embed the host name."""
    reason = getattr(exc, "reason", None)
    if isinstance(exc, urllib.error.URLError) and isinstance(reason, BaseException):
        return f"{type(exc).__name__} ({type(reason).__name__})"
    return type(exc).__name__


class Fetcher:
    """`opener(request, timeout=...)` returns a response; the default is urllib's own opener."""

    def __init__(
        self,
        source: SourceConfig,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.source = source
        self._open = opener if opener is not None else urllib.request.build_opener().open
        self.sleep = sleep
        self.request_count = 0
        self.blocked = False

    def get(self, path: str) -> str:
        if self.blocked:
            raise BlockedError(f"Not requesting {path}: an earlier request was blocked")
        url = self.source.base_url + "/" + path.lstrip("/")
        problem = "no attempts made"
        for attempt in range(self.source.retries):
            if self.request_count:
                self.sleep(random.uniform(*self.source.delay_s))
            if attempt:
                self.sleep(2**attempt)
            self.request_count += 1
            log.info("GET %s", path)
            request = urllib.request.Request(url, headers={"User-Agent": self.source.user_agent})
            try:
                with self._open(request, timeout=self.source.timeout_s) as response:
                    status = response.status
                    text = _decode(response.read(), response.headers.get_content_charset())
            except urllib.error.HTTPError as exc:
                status = exc.code
                try:
                    text = _decode(exc.read(), None)
                except (OSError, http.client.HTTPException):
                    text = ""
            except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
                problem = _problem(exc)
                log.warning("Request for %s failed (attempt %d/%d): %s", path, attempt + 1,
                            self.source.retries, problem)
                continue
            if status in BLOCK_STATUSES or is_block_page(text):
                self.blocked = True
                raise BlockedError(f"HTTP {status} for {path}: the site is blocking automated requests")
            if status >= 500:
                problem = f"HTTP {status}"
                log.warning("Server error for %s (attempt %d/%d): %s", path, attempt + 1,
                            self.source.retries, problem)
                continue
            if status != 200:
                raise FetchError(f"HTTP {status} for {path}")
            return text
        raise FetchError(f"Gave up on {path} after {self.source.retries} attempts: {problem}")
