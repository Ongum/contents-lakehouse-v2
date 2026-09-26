"""Advertising document collection models, envelope, and orchestration."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

if __package__:
    from .bronze_storage import BronzeStorageError
else:
    from bronze_storage import BronzeStorageError


COLLECTOR_VERSION = "advertising-http/1.0"
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
    observation_key: str | None = None
    content_created: bool = False


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


def safe_url(value: str) -> str:
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


def validate_source_config(config: SourceConfig) -> None:
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
        "source_url": safe_url(config.source_url),
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


def collect_source(
    config: SourceConfig,
    adapter: SourceAdapter,
    storage: Any,
    run_id: str | None = None,
    retrieved_at: str | None = None,
) -> CollectionResult:
    observed_at = retrieved_at or utc_now()
    try:
        validate_source_config(config)
        observed_at = storage.observation_time(observed_at)
        document = adapter.fetch(config)
        previous_hash = storage.latest_content_hash(config)
        record = build_bronze_record(
            config,
            document,
            run_id or str(uuid4()),
            observed_at,
            previous_hash,
        )
        record['observation_contract'] = 'advertising-observation/1'
        object_key, created = storage.write_version(record)
        observation_key, _ = storage.write_observation(record, object_key)
        history = storage.list_source_observations(config)
        position = next(index for index, item in enumerate(history) if item[0] == observation_key)
        previous_hash = history[position - 1][1]['content_hash'] if position else None
        changed = None if previous_hash is None else previous_hash != document.content_hash
        attempts = getattr(adapter, "last_attempts", 1)
        _, persisted = storage.resolve_observation(
            observation_key, history[position][1], previous_hash
        )
        return CollectionResult(
            status=CollectionStatus.SUCCESS if created or changed is True else CollectionStatus.UNCHANGED,
            retrieved_at=observed_at,
            attempts=attempts,
            object_key=object_key,
            content_hash=document.content_hash,
            content_changed=changed,
            record=persisted,
            observation_key=observation_key,
            content_created=created,
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
