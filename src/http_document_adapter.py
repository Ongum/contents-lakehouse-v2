"""Lightweight HTTP document transport for advertising source collection."""

import base64
import re
import socket
import time
from hashlib import sha256
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

if __package__:
    from .advertising_collection import (
        FetchedDocument,
        MalformedDocumentError,
        SourceConfig,
        SourceFetchError,
        canonicalize_content,
        content_hash,
        safe_url,
        sanitize_metadata,
        validate_source_config,
    )
else:
    from advertising_collection import (
        FetchedDocument,
        MalformedDocumentError,
        SourceConfig,
        SourceFetchError,
        canonicalize_content,
        content_hash,
        safe_url,
        sanitize_metadata,
        validate_source_config,
    )


USER_AGENT = "ContentsLakehouseMVP/1.0 (+advertising-source-collector)"
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _header(headers: Any, name: str) -> str | None:
    value = headers.get(name) if headers is not None else None
    return str(value) if value is not None else None


def _decode_body(
    body: bytes, content_type_header: str | None
) -> tuple[str, str, int]:
    if not body:
        raise MalformedDocumentError("HTTP response body is empty.")
    media_type = (content_type_header or "").split(";", 1)[0].strip().lower()
    text_types = (
        media_type.startswith("text/")
        or media_type
        in {
            "application/json",
            "application/ld+json",
            "application/xml",
            "application/xhtml+xml",
        }
    )
    if not text_types:
        raise MalformedDocumentError(
            f"Unsupported or missing document content type: {media_type or 'unknown'}."
        )
    charset_match = re.search(
        r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type_header or "", re.I
    )
    charset = charset_match.group(1) if charset_match else "utf-8"
    candidates = [charset]
    if charset.casefold().replace("_", "-") in {"euc-kr", "ks-c-5601-1987"}:
        candidates.append("cp949")
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return body.decode(candidate, errors="strict"), candidate.lower(), 0
        except (LookupError, UnicodeDecodeError) as error:
            last_error = error
    legacy_korean = charset.casefold().replace("_", "-") in {
        "euc-kr",
        "ks-c-5601-1987",
    }
    if legacy_korean:
        decoded = body.decode("cp949", errors="replace")
        return decoded, "cp949", decoded.count("\ufffd")
    raise MalformedDocumentError(
        f"Response cannot be decoded with declared charset {charset}."
    ) from last_error


class HttpDocumentAdapter:
    """Small HTTP adapter with bounded retries and robots enforcement."""

    def __init__(
        self,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        max_content_bytes: int = 5_000_000,
        identity_canonicalizer: Callable[[str], tuple[str, str | None]] | None = None,
    ) -> None:
        self.opener = opener
        self.sleeper = sleeper
        self.max_content_bytes = max_content_bytes
        self.identity_canonicalizer = identity_canonicalizer
        self.last_attempts = 0

    def _check_robots(self, config: SourceConfig) -> None:
        parsed = urlsplit(config.source_url)
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        request = Request(robots_url, headers={"User-Agent": USER_AGENT})
        try:
            with self.opener(request, timeout=config.timeout_seconds) as response:
                body = response.read(500_001)
        except HTTPError as error:
            if error.code == 404:
                return
            raise SourceFetchError(
                f"Unable to verify robots policy: HTTP {error.code}.",
                error.code in RETRYABLE_HTTP_STATUS,
                0,
            ) from error
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise SourceFetchError(
                "Unable to verify robots policy safely.", True, 0
            ) from error
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(body.decode("utf-8", errors="replace").splitlines())
        if not parser.can_fetch(USER_AGENT, config.source_url):
            raise SourceFetchError(
                "Collection is disallowed by the source robots policy.", False, 0
            )

    def fetch(self, config: SourceConfig) -> FetchedDocument:
        validate_source_config(config)
        if config.respect_robots:
            self._check_robots(config)
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9",
        }
        request = Request(config.source_url, headers=request_headers)

        for attempt in range(1, config.max_attempts + 1):
            self.last_attempts = attempt
            try:
                with self.opener(request, timeout=config.timeout_seconds) as response:
                    status = int(getattr(response, "status", response.getcode()))
                    if not 200 <= status < 300:
                        raise HTTPError(
                            config.source_url, status, "Unexpected HTTP status", {}, None
                        )
                    body = response.read(self.max_content_bytes + 1)
                    if len(body) > self.max_content_bytes:
                        raise MalformedDocumentError(
                            "HTTP response exceeds the configured size limit."
                        )
                    content_type_header = _header(response.headers, "Content-Type")
                    decoded, charset, decode_replacements = _decode_body(
                        body, content_type_header
                    )
                    normalized = canonicalize_content(decoded)
                    identity_content = normalized
                    identity_rule = None
                    if self.identity_canonicalizer is not None:
                        identity_content, identity_rule = self.identity_canonicalizer(
                            normalized
                        )
                    final_url = (
                        response.geturl()
                        if hasattr(response, "geturl")
                        else config.source_url
                    )
                    metadata = {
                        "method": "GET",
                        "timeout_seconds": config.timeout_seconds,
                        "max_attempts": config.max_attempts,
                        "request_headers": request_headers,
                        "response": {
                            "status": status,
                            "content_type": content_type_header,
                            "charset": charset,
                            "decode_replacement_count": decode_replacements,
                            "final_url": safe_url(final_url),
                            "etag": _header(response.headers, "ETag"),
                            "last_modified": _header(
                                response.headers, "Last-Modified"
                            ),
                        },
                    }
                    if identity_rule:
                        metadata["content_identity"] = {
                            "canonicalization": identity_rule
                        }
                    return FetchedDocument(
                        raw_content=normalized,
                        content_hash=content_hash(identity_content),
                        request_metadata=sanitize_metadata(metadata),
                        raw_content_bytes_base64=base64.b64encode(body).decode("ascii"),
                        raw_content_bytes_hash=sha256(body).hexdigest(),
                        raw_content_text_hash=content_hash(normalized),
                    )
            except MalformedDocumentError:
                raise
            except HTTPError as error:
                retryable = error.code in RETRYABLE_HTTP_STATUS
                if not retryable or attempt == config.max_attempts:
                    raise SourceFetchError(
                        f"HTTP collection failed with status {error.code}.",
                        retryable,
                        attempt,
                    ) from error
            except (URLError, TimeoutError, socket.timeout, OSError) as error:
                if attempt == config.max_attempts:
                    raise SourceFetchError(
                        "HTTP collection failed after a network error.", True, attempt
                    ) from error
            self.sleeper(min(2.0, 0.25 * (2 ** (attempt - 1))))
        raise AssertionError("Unreachable retry state.")
