"""Immutable Bronze persistence for provisional advertising discovery evidence."""

import json
import re
from hashlib import sha256
from typing import Any

if __package__:
    from .advertising_collection import sanitize_metadata
    from .advertising_discovery import _source_name, _utc_timestamp, normalize_discovery_url
    from .bronze_storage import BronzeStorage, BronzeStorageError
else:
    from advertising_collection import sanitize_metadata
    from advertising_discovery import _source_name, _utc_timestamp, normalize_discovery_url
    from bronze_storage import BronzeStorage, BronzeStorageError


DISCOVERY_FIELDS = {
    "discovery_source",
    "query",
    "source_url",
    "discovered_at",
    "raw_content",
    "content_hash",
    "request_metadata",
}


def build_discovery_record(
    *,
    discovery_source: str,
    query: str,
    source_url: str,
    discovered_at: str,
    raw_content: str,
    request_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_content, str) or not raw_content:
        raise ValueError("raw_content is required.")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required.")
    normalized_content = raw_content.replace("\r\n", "\n").replace("\r", "\n")
    return {
        "discovery_source": _source_name(discovery_source),
        "query": query.strip(),
        "source_url": normalize_discovery_url(source_url),
        "discovered_at": _utc_timestamp(discovered_at),
        "raw_content": normalized_content,
        "content_hash": sha256(normalized_content.encode("utf-8")).hexdigest(),
        "request_metadata": sanitize_metadata(request_metadata or {}),
    }


class AdvertisingDiscoveryBronzeStorage(BronzeStorage):
    CONDITIONAL_CONFLICT_CODES = {
        "PreconditionFailed",
        "ConditionalRequestConflict",
    }

    @classmethod
    def object_name(cls, record: dict[str, Any]) -> str:
        source = _source_name(record.get("discovery_source"))
        source_url = normalize_discovery_url(record.get("source_url"))
        content_hash = record.get("content_hash")
        if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise BronzeStorageError("Invalid discovery content_hash.")
        source_id = sha256(source_url.encode("utf-8")).hexdigest()
        return (
            f"bronze/advertising_discovery/{source}/source_id={source_id}/"
            f"content_hash={content_hash}/document.json"
        )

    @staticmethod
    def serialize_record(record: dict[str, Any]) -> bytes:
        missing = DISCOVERY_FIELDS - record.keys()
        if missing:
            raise BronzeStorageError(
                "Discovery Bronze record is missing fields: "
                + ", ".join(sorted(missing))
            )
        expected = build_discovery_record(
            discovery_source=record["discovery_source"],
            query=record["query"],
            source_url=record["source_url"],
            discovered_at=record["discovered_at"],
            raw_content=record["raw_content"],
            request_metadata=record["request_metadata"],
        )
        if expected != record:
            raise BronzeStorageError("Discovery Bronze record is not canonical or contains secrets.")
        return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    def write_capture(self, record: dict[str, Any]) -> tuple[str, bool]:
        content = self.serialize_record(record)
        object_name = self.object_name(record)
        try:
            self.client._put_object(
                self.bucket,
                object_name,
                content,
                headers={"Content-Type": "application/json", "If-None-Match": "*"},
            )
        except Exception as error:
            if getattr(error, "code", None) not in self.CONDITIONAL_CONFLICT_CODES:
                raise BronzeStorageError(
                    f"Unable to create discovery Bronze object {object_name}."
                ) from error
            existing = self.read_record(object_name)
            identity = ("discovery_source", "query", "source_url", "content_hash")
            if not all(existing.get(field) == record[field] for field in identity):
                raise BronzeStorageError(
                    f"Discovery Bronze object has conflicting identity: {object_name}."
                )
            return object_name, False
        return object_name, True
