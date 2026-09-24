"""Small unauthenticated Google News KR RSS discovery adapter."""

import html
import re
import socket
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "ContentsLakehouseMVP/1.0 (+artist-advertising-discovery)"


@dataclass(frozen=True)
class DiscoverySearchResult:
    title: str
    url: str
    snippet: str | None
    publication_date: str | None


@dataclass(frozen=True)
class DiscoverySearchPage:
    query: str
    search_url: str
    raw_content: str
    request_metadata: dict[str, Any]
    results: tuple[DiscoverySearchResult, ...]


class DiscoverySearchError(RuntimeError):
    pass


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?s)<[^>]+>", " ", value)
    normalized = " ".join(html.unescape(text).split())
    return normalized or None


def parse_google_news_rss(content: bytes) -> list[DiscoverySearchResult]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise DiscoverySearchError("Discovery source returned invalid RSS.") from error
    results = []
    for item in root.findall("./channel/item"):
        title = _plain_text(item.findtext("title"))
        url = item.findtext("link")
        if not title or not url:
            continue
        published = None
        published_text = item.findtext("pubDate")
        if published_text:
            try:
                published = (
                    parsedate_to_datetime(published_text)
                    .astimezone(timezone.utc)
                    .date()
                    .isoformat()
                )
            except (TypeError, ValueError):
                published = None
        description = _plain_text(item.findtext("description"))
        if description == title:
            description = None
        results.append(DiscoverySearchResult(title, url.strip(), description, published))
    return results


class GoogleNewsKrRssAdapter:
    source_name = "google_news_kr"

    def __init__(
        self,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 10.0,
        max_attempts: int = 2,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        self.opener = opener
        self.sleeper = sleeper
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.max_response_bytes = max_response_bytes

    @staticmethod
    def search_url(query: str) -> str:
        parameters = urlencode(
            {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
        )
        return f"https://news.google.com/rss/search?{parameters}"

    def fetch_first_page(self, query: str) -> list[DiscoverySearchResult]:
        return list(self.fetch_first_page_capture(query).results)

    def fetch_first_page_capture(self, query: str) -> DiscoverySearchPage:
        """Fetch one result page and retain its raw response for Bronze."""
        search_url = self.search_url(query)
        request = Request(
            search_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml"},
        )
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    content = response.read(self.max_response_bytes + 1)
                    status = int(getattr(response, "status", response.getcode()))
                    content_type = response.headers.get("Content-Type")
                    final_url = response.geturl()
                if len(content) > self.max_response_bytes:
                    raise DiscoverySearchError("Discovery RSS response is too large.")
                try:
                    raw_content = content.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise DiscoverySearchError(
                        "Discovery RSS response is not valid UTF-8."
                    ) from error
                return DiscoverySearchPage(
                    query=query,
                    search_url=search_url,
                    raw_content=raw_content,
                    request_metadata={
                        "method": "GET",
                        "timeout_seconds": self.timeout_seconds,
                        "max_attempts": self.max_attempts,
                        "response": {
                            "status": status,
                            "content_type": content_type,
                            "final_url": final_url,
                        },
                    },
                    results=tuple(parse_google_news_rss(content)),
                )
            except DiscoverySearchError:
                raise
            except HTTPError as error:
                retryable = error.code in {408, 425, 429, 500, 502, 503, 504}
                if not retryable or attempt == self.max_attempts:
                    raise DiscoverySearchError(
                        f"Discovery search failed with HTTP {error.code}."
                    ) from error
            except (URLError, TimeoutError, socket.timeout, OSError) as error:
                if attempt == self.max_attempts:
                    raise DiscoverySearchError(
                        "Discovery search failed after a network error."
                    ) from error
            self.sleeper(0.25 * attempt)
        raise AssertionError("Unreachable discovery retry state.")
