"""Immutable MinIO persistence for advertising Bronze documents."""

import base64
import json
import re
from hashlib import sha256
from typing import Any

if __package__:
    from .advertising_collection import (
        ADVERTISING_FIELDS,
        AdvertisingStorageConflict,
        SourceConfig,
        content_hash,
        sanitize_metadata,
    )
    from .bronze_storage import BronzeStorage, BronzeStorageError
else:
    from advertising_collection import (
        ADVERTISING_FIELDS,
        AdvertisingStorageConflict,
        SourceConfig,
        content_hash,
        sanitize_metadata,
    )
    from bronze_storage import BronzeStorage, BronzeStorageError


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
