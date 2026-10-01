"""HTTP fetching shared by every provider implementation."""

from __future__ import annotations

import http.client
import sys
import time
import urllib.error
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TIMEOUT = 20
ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "free-llm-model-fetcher/1.0"


def one_line(value: object) -> str:
    """Return ``value`` as a single line of printable text.

    Upstream servers control part of their own error text, so an embedded
    escape sequence or newline could restyle a CI log or forge extra lines.
    """
    return " ".join(safe_text(value).split())


def safe_text(value: object) -> str:
    """Return ``value`` with every non-printable character replaced by a space.

    Line breaks are kept so multi-line text such as a traceback stays readable.
    """
    return "".join(
        char if char.isprintable() or char == "\n" else " " for char in str(value)
    )


class _SameHostHTTPSRedirect(HTTPRedirectHandler):
    """Follow a redirect only while it stays on https and on the same host.

    urllib copies the request's ordinary headers onto the redirected request,
    which would otherwise replay credentials to any host the server names.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            reason = f"insecure redirect scheme: {one_line(newurl)}"
            raise urllib.error.HTTPError(newurl, code, reason, headers, fp)
        if urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            reason = f"cross-host redirect: {one_line(newurl)}"
            raise urllib.error.HTTPError(newurl, code, reason, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = build_opener(_SameHostHTTPSRedirect())


def get_url(url: str, headers: dict[str, str] | None = None) -> bytes:
    """Fetch a URL, retrying transient network and server failures.

    Args:
        url: The HTTPS URL to fetch. A redirect that leaves https or the
            original host is refused instead of followed.
        headers: Optional HTTP headers to send. They go on as unredirected
            headers so a credential never travels to a redirect target, and
            the default User-Agent is always kept.

    Returns:
        The response body as bytes.

    Raises:
        ValueError: If the URL does not use the ``https://`` scheme or the
            response is larger than ``MAX_RESPONSE_BYTES``.
        urllib.error.URLError: If every attempt fails.
    """
    if not url.startswith("https://"):
        raise ValueError(f"unsafe URL scheme: {one_line(url)}")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for name, value in (headers or {}).items():
        request.add_unredirected_header(name, value)
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with OPENER.open(request, timeout=TIMEOUT) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"response from {one_line(url)} exceeds {MAX_RESPONSE_BYTES} bytes"
                )
            return body
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS or attempt == ATTEMPTS:
                raise
            _retry(url, attempt, error)
        except (
            urllib.error.URLError,
            TimeoutError,
            http.client.HTTPException,
        ) as error:
            if attempt == ATTEMPTS:
                raise
            _retry(url, attempt, error)


def _retry(url: str, attempt: int, error: BaseException) -> None:
    wait = BACKOFF_SECONDS * attempt
    print(
        f"retrying {one_line(url)} in {wait}s after "
        f"{type(error).__name__}: {one_line(error)}",
        file=sys.stderr,
    )
    time.sleep(wait)
