"""Reusable HTTP-document collection and immutable advertising Bronze storage."""

import base64
import json
import re
import socket
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
from uuid import uuid4

if __package__:
    from .bronze_storage import BronzeStorage, BronzeStorageError
else:
    from bronze_storage import BronzeStorage, BronzeStorageError


COLLECTOR_VERSION = "advertising-http/1.0"
USER_AGENT = "ContentsLakehouseMVP/1.0 (+advertising-source-collector)"
SENSITIVE_NORMALIZED_NAMES = {
    "apikey",
    "xapikey",
    "accesstoken",
    "authtoken",
    "clientsecret",
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "password",
    "passwd",
    "secret",
    "token",
    "signature",
    "sig",
}
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
ADVERTISING_FIELDS = {
    "source_type",
    "source_name",
    "source_url",
    "source_identifier",
    "retrieved_at",
    "published_at",
    "content_hash",
    "previous_content_hash",
    "content_changed",
    "run_id",
    "collector_version",
    "raw_content",
    "raw_content_text_hash",
    "raw_content_bytes_base64",
    "raw_content_bytes_hash",
    "request_metadata",
}


class CollectionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    UNCHANGED = "UNCHANGED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class SourceConfig:
    source_type: str
    source_name: str
    source_url: str
    source_identifier: str
    published_at: str | None = None
    timeout_seconds: float = 15.0
    max_attempts: int = 3
    respect_robots: bool = True


@dataclass(frozen=True)
class FetchedDocument:
    raw_content: str
    content_hash: str
    request_metadata: dict[str, Any]
    raw_content_bytes_base64: str | None = None
    raw_content_bytes_hash: str | None = None
    raw_content_text_hash: str | None = None


@dataclass(frozen=True)
class CollectionResult:
    status: CollectionStatus
    retrieved_at: str
    attempts: int
    object_key: str | None = None
    content_hash: str | None = None
    content_changed: bool | None = None
    record: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None


class SourceAdapter(Protocol):
    def fetch(self, config: SourceConfig) -> FetchedDocument:
        """Fetch and normalize one configured source document."""


class SourceFetchError(Exception):
    def __init__(self, message: str, retryable: bool, attempts: int) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.attempts = attempts


class MalformedDocumentError(Exception):
    """Raised when a response was received but cannot be safely preserved."""


class AdvertisingStorageConflict(BronzeStorageError):
    """Raised instead of overwriting a conflicting deterministic object key."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonicalize_content(content: str) -> str:
    """Normalize representation without extracting or changing document meaning."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalized.lstrip("\ufeff"))


def content_hash(content: str) -> str:
    return sha256(canonicalize_content(content).encode("utf-8")).hexdigest()


def is_sensitive_name(name: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(name).casefold())
    return normalized in SENSITIVE_NORMALIZED_NAMES


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_metadata(item)
            for key, item in value.items()
            if not is_sensitive_name(key)
        }
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    return value


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    safe_query = urlencode(
        [
            (name, "REDACTED" if is_sensitive_name(name) else item)
            for name, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, safe_query, ""))


def _validate_config(config: SourceConfig) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", config.source_type):
        raise ValueError("source_type must be a safe lowercase identifier.")
    if not config.source_name or not config.source_identifier:
        raise ValueError("source_name and source_identifier are required.")
    parsed = urlsplit(config.source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise ValueError("source_url must not contain credentials.")
    if any(
        is_sensitive_name(name)
        for name, _ in parse_qsl(parsed.query, keep_blank_values=True)
    ):
        raise ValueError("source_url must not contain secret query parameters.")
    if config.timeout_seconds <= 0 or not 1 <= config.max_attempts <= 5:
        raise ValueError("Invalid timeout or max_attempts.")


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
        or media_type in {
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
        _validate_config(config)
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
                            "final_url": _safe_url(final_url),
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


def build_bronze_record(
    config: SourceConfig,
    document: FetchedDocument,
    run_id: str,
    retrieved_at: str,
    previous_content_hash: str | None,
) -> dict[str, Any]:
    return {
        "source_type": config.source_type,
        "source_name": config.source_name,
        "source_url": _safe_url(config.source_url),
        "source_identifier": config.source_identifier,
        "retrieved_at": retrieved_at,
        "published_at": config.published_at,
        "content_hash": document.content_hash,
        "previous_content_hash": previous_content_hash,
        "content_changed": (
            None
            if previous_content_hash is None
            else previous_content_hash != document.content_hash
        ),
        "run_id": run_id,
        "collector_version": COLLECTOR_VERSION,
        "raw_content": document.raw_content,
        "raw_content_text_hash": (
            document.raw_content_text_hash or content_hash(document.raw_content)
        ),
        "raw_content_bytes_base64": document.raw_content_bytes_base64,
        "raw_content_bytes_hash": document.raw_content_bytes_hash,
        "request_metadata": sanitize_metadata(document.request_metadata),
    }


class AdvertisingBronzeStorage(BronzeStorage):
    CONDITIONAL_CONFLICT_CODES = {
        "PreconditionFailed",
        "ConditionalRequestConflict",
    }

    @staticmethod
    def source_digest(source_type: str, source_identifier: str) -> str:
        return sha256(f"{source_type}\0{source_identifier}".encode("utf-8")).hexdigest()

    @classmethod
    def source_prefix(cls, source_type: str, source_identifier: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", source_type):
            raise BronzeStorageError("Invalid advertising source_type.")
        digest = cls.source_digest(source_type, source_identifier)
        return f"bronze/advertising/{source_type}/source_id={digest}/"

    @classmethod
    def object_name(cls, record: dict[str, Any]) -> str:
        digest = record.get("content_hash")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BronzeStorageError("Invalid advertising content_hash.")
        return (
            cls.source_prefix(record["source_type"], record["source_identifier"])
            + f"content_hash={digest}/document.json"
        )

    @staticmethod
    def serialize_record(record: dict[str, Any]) -> bytes:
        missing = ADVERTISING_FIELDS - record.keys()
        if missing:
            raise BronzeStorageError(
                "Advertising Bronze record is missing fields: "
                f"{', '.join(sorted(missing))}."
            )
        if content_hash(record.get("raw_content", "")) != record["raw_content_text_hash"]:
            raise BronzeStorageError("Advertising raw_content text hash does not match.")
        if not re.fullmatch(r"[0-9a-f]{64}", record["content_hash"]):
            raise BronzeStorageError("Advertising content identity hash is invalid.")
        encoded_bytes = record.get("raw_content_bytes_base64")
        bytes_hash = record.get("raw_content_bytes_hash")
        if (encoded_bytes is None) != (bytes_hash is None):
            raise BronzeStorageError("Advertising raw byte provenance is incomplete.")
        if encoded_bytes is not None:
            try:
                original_bytes = base64.b64decode(encoded_bytes, validate=True)
            except (ValueError, TypeError) as error:
                raise BronzeStorageError(
                    "Advertising raw_content_bytes_base64 is invalid."
                ) from error
            if sha256(original_bytes).hexdigest() != bytes_hash:
                raise BronzeStorageError("Advertising raw byte hash does not match.")
        safe_metadata = sanitize_metadata(record.get("request_metadata"))
        if safe_metadata != record.get("request_metadata"):
            raise BronzeStorageError("Advertising request_metadata contains secrets.")
        try:
            return json.dumps(
                record, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise BronzeStorageError(
                "Advertising Bronze record is not JSON serializable."
            ) from error

    def list_source_versions(
        self, config: SourceConfig
    ) -> list[tuple[str, dict[str, Any]]]:
        return self.list_records(
            prefix=self.source_prefix(config.source_type, config.source_identifier)
        )

    def latest_content_hash(self, config: SourceConfig) -> str | None:
        versions = self.list_source_versions(config)
        if not versions:
            return None
        latest = max(versions, key=lambda item: item[1].get("retrieved_at", ""))
        value = latest[1].get("content_hash")
        return value if isinstance(value, str) else None

    def write_version(self, record: dict[str, Any]) -> tuple[str, bool]:
        content = self.serialize_record(record)
        object_name = self.object_name(record)
        try:
            # minio-py 7.2.x does not expose If-None-Match on public put_object().
            # Its single-request helper passes signed headers to S3/MinIO, where
            # If-None-Match: * atomically permits only creation of a missing key.
            self.client._put_object(
                self.bucket,
                object_name,
                content,
                headers={
                    "Content-Type": "application/json",
                    "If-None-Match": "*",
                },
            )
        except Exception as error:
            if getattr(error, "code", None) not in self.CONDITIONAL_CONFLICT_CODES:
                raise BronzeStorageError(
                    f"Unable to create advertising Bronze object {object_name}."
                ) from error
            try:
                existing_content = self._read_bytes(object_name)
            except Exception as read_error:
                raise BronzeStorageError(
                    "Conditional advertising Bronze write lost a race, but the "
                    f"existing object could not be verified: {object_name}."
                ) from read_error
            try:
                existing = json.loads(existing_content)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise AdvertisingStorageConflict(
                    f"Invalid existing advertising Bronze object {object_name}."
                ) from error
            try:
                self.serialize_record(existing)
            except BronzeStorageError as error:
                raise AdvertisingStorageConflict(
                    f"Invalid existing advertising Bronze object {object_name}."
                ) from error
            identity = ("source_type", "source_identifier", "content_hash")
            if not all(existing.get(field) == record[field] for field in identity):
                raise AdvertisingStorageConflict(
                    f"Advertising Bronze object has conflicting identity: {object_name}."
                )
            return object_name, False
        return object_name, True


def collect_source(
    config: SourceConfig,
    adapter: SourceAdapter,
    storage: AdvertisingBronzeStorage,
    run_id: str | None = None,
    retrieved_at: str | None = None,
) -> CollectionResult:
    observed_at = retrieved_at or utc_now()
    try:
        _validate_config(config)
        document = adapter.fetch(config)
        previous_hash = storage.latest_content_hash(config)
        record = build_bronze_record(
            config,
            document,
            run_id or str(uuid4()),
            observed_at,
            previous_hash,
        )
        object_key, created = storage.write_version(record)
        attempts = getattr(adapter, "last_attempts", 1)
        if created:
            return CollectionResult(
                status=CollectionStatus.SUCCESS,
                retrieved_at=observed_at,
                attempts=attempts,
                object_key=object_key,
                content_hash=document.content_hash,
                content_changed=record["content_changed"],
                record=record,
            )
        persisted = storage.read_record(object_key)
        return CollectionResult(
            status=CollectionStatus.UNCHANGED,
            retrieved_at=observed_at,
            attempts=attempts,
            object_key=object_key,
            content_hash=document.content_hash,
            content_changed=False,
            record=persisted,
        )
    except MalformedDocumentError as error:
        return CollectionResult(
            CollectionStatus.QUARANTINED,
            observed_at,
            getattr(adapter, "last_attempts", 1),
            error_type="malformed_response",
            error_message=str(error),
        )
    except SourceFetchError as error:
        return CollectionResult(
            (
                CollectionStatus.RETRYABLE_FAILURE
                if error.retryable
                else CollectionStatus.PERMANENT_FAILURE
            ),
            observed_at,
            error.attempts,
            error_type="http_collection_error",
            error_message=str(error),
        )
    except AdvertisingStorageConflict as error:
        return CollectionResult(
            CollectionStatus.QUARANTINED,
            observed_at,
            getattr(adapter, "last_attempts", 1),
            error_type="storage_conflict",
            error_message=str(error),
        )
    except ValueError as error:
        return CollectionResult(
            CollectionStatus.PERMANENT_FAILURE,
            observed_at,
            getattr(adapter, "last_attempts", 1),
            error_type="collection_configuration_error",
            error_message=str(error),
        )
    except BronzeStorageError as error:
        return CollectionResult(
            CollectionStatus.RETRYABLE_FAILURE,
            observed_at,
            getattr(adapter, "last_attempts", 1),
            error_type="storage_error",
            error_message=str(error),
        )
