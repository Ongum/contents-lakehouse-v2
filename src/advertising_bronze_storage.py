"""Immutable MinIO persistence for advertising Bronze documents."""

import base64
import json
import re
from datetime import datetime, timezone
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
        return [item for item in self.list_records(
            prefix=self.source_prefix(config.source_type, config.source_identifier)
        ) if item[0].endswith('/document.json')]

    @staticmethod
    def observation_time(value: str) -> str:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Advertising observation time requires a timezone.')
        return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')

    def write_observation(self, record: dict[str, Any], reference: str) -> tuple[str, bool]:
        """Append a collection occurrence after its immutable content is durable."""
        self.serialize_record(record)
        observed_at = self.observation_time(record['retrieved_at'])
        if not isinstance(record['run_id'], str) or not record['run_id']:
            raise ValueError('Advertising observation requires run_id.')
        identity = json.dumps([record['source_type'], record['source_identifier'],
                               record['run_id'], observed_at], separators=(',', ':'))
        observation_id = sha256(identity.encode()).hexdigest()
        observation = {
            name: record[name] for name in (
                'source_type', 'source_identifier', 'source_name', 'source_url',
                'run_id', 'published_at', 'collector_version', 'content_hash',
                'raw_content_text_hash', 'raw_content_bytes_hash', 'request_metadata',
            )
        }
        observation.update(record_type='advertising_observation',
                           observation_id=observation_id, retrieved_at=observed_at,
                           content_reference=reference)
        if reference != self.object_name(record):
            raise AdvertisingStorageConflict('Observation content reference mismatch.')
        # Also protects callers that bypass collect_source from dangling references.
        self._validated_content(reference)
        key = self.source_prefix(record['source_type'], record['source_identifier']) + (
            f'observations/{observation_id}.json'
        )
        content = json.dumps(observation, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')
        try:
            self.client._put_object(self.bucket, key, content, headers={
                'Content-Type': 'application/json', 'If-None-Match': '*',
            })
        except Exception as error:
            if getattr(error, 'code', None) not in self.CONDITIONAL_CONFLICT_CODES:
                raise BronzeStorageError(f'Unable to write observation {key}.') from error
            if self.read_record(key) != observation:
                raise AdvertisingStorageConflict(f'Conflicting observation: {key}.') from error
            return key, False
        return key, True

    def list_source_observations(self, config: SourceConfig) -> list[tuple[str, dict[str, Any]]]:
        """Include original legacy captures, without inventing missed observations."""
        records = self.list_records(prefix=self.source_prefix(
            config.source_type, config.source_identifier))
        observations = [item for item in records
                        if item[1].get('record_type') == 'advertising_observation']
        represented = {(row['content_reference'], row['run_id'],
                        self.observation_time(row['retrieved_at'])) for _, row in observations}
        for key, row in records:
            if not key.endswith('/document.json'):
                continue
            if row.get('observation_contract') == 'advertising-observation/1':
                continue
            observed_at = self.observation_time(row['retrieved_at'])
            if (key, row['run_id'], observed_at) not in represented:
                observations.append((key, dict(row, retrieved_at=observed_at,
                                               content_reference=key)))
        return sorted(observations, key=lambda item: (item[1]['retrieved_at'], item[0]))

    def latest_source_record(self, config: SourceConfig) -> tuple[str, dict[str, Any]] | None:
        observations = self.list_source_observations(config)
        if not observations:
            return None
        key, observation = observations[-1]
        previous_hash = observations[-2][1]['content_hash'] if len(observations) > 1 else None
        return self.resolve_observation(key, observation, previous_hash)

    def resolve_observation(
        self, key: str, observation: dict[str, Any], previous_hash: str | None
    ) -> tuple[str, dict[str, Any]]:
        """Resolve content without changing the envelope consumed by existing Silver."""
        reference = observation['content_reference']
        record = self._validated_content(reference)
        if record['content_hash'] != observation['content_hash']:
            raise AdvertisingStorageConflict('Observation content identity mismatch.')
        metadata = {name: value for name, value in observation.items()
                    if name not in {'raw_content', 'raw_content_bytes_base64'}}
        metadata.update(previous_content_hash=previous_hash,
                        content_changed=None if previous_hash is None else
                        previous_hash != observation['content_hash'])
        return reference, dict(record, observation_reference=key, observation=metadata)

    def _validated_content(self, reference: str) -> dict[str, Any]:
        record = self.read_record(reference)
        try:
            self.serialize_record(record)
            if self.object_name(record) != reference:
                raise AdvertisingStorageConflict('Stored content identity mismatch.')
        except (BronzeStorageError, KeyError, TypeError, ValueError) as error:
            raise AdvertisingStorageConflict(f'Invalid stored content: {reference}.') from error
        return record

    def latest_content_hash(self, config: SourceConfig) -> str | None:
        latest = self.latest_source_record(config)
        if latest is None:
            return None
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
