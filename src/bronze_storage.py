"""Persist immutable Bronze API-response records to MinIO."""

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit


BRONZE_FIELDS = {
    "run_id",
    "source",
    "resource",
    "ingested_at",
    "request_context",
    "raw_payload",
}
SECRET_NAMES = {"key", "api_key", "youtube_api_key"}


class BronzeStorageError(Exception):
    """Raised when Bronze persistence cannot complete safely."""


@dataclass(frozen=True)
class MinioSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool

    @classmethod
    def from_environment(cls) -> "MinioSettings":
        values = {
            name: os.environ.get(name, "").strip()
            for name in (
                "MINIO_ENDPOINT",
                "MINIO_ACCESS_KEY",
                "MINIO_SECRET_KEY",
                "MINIO_BUCKET",
            )
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise BronzeStorageError(
                f"Missing MinIO configuration: {', '.join(missing)}."
            )

        parsed = urlsplit(values["MINIO_ENDPOINT"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BronzeStorageError(
                "MINIO_ENDPOINT must be an http:// or https:// endpoint."
            )
        if parsed.path not in {"", "/"}:
            raise BronzeStorageError("MINIO_ENDPOINT must not contain a path.")

        return cls(
            endpoint=parsed.netloc,
            access_key=values["MINIO_ACCESS_KEY"],
            secret_key=values["MINIO_SECRET_KEY"],
            bucket=values["MINIO_BUCKET"],
            secure=parsed.scheme == "https",
        )


class BronzeStorage:
    def __init__(self, client: Any, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_environment(cls) -> "BronzeStorage":
        settings = MinioSettings.from_environment()
        try:
            from minio import Minio
        except ImportError as error:
            raise BronzeStorageError(
                "MinIO client is not installed. Run: pip install -r requirements.txt"
            ) from error

        client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )
        return cls(client, settings.bucket)

    def ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except Exception as error:
            raise BronzeStorageError(
                f"Unable to prepare MinIO bucket {self.bucket}."
            ) from error

    @staticmethod
    def serialize_record(record: dict[str, Any]) -> bytes:
        missing = BRONZE_FIELDS - record.keys()
        if missing:
            raise BronzeStorageError(
                f"Bronze record is missing fields: {', '.join(sorted(missing))}."
            )
        request_context = record["request_context"]
        if not isinstance(request_context, dict):
            raise BronzeStorageError("Bronze request_context must be an object.")
        if any(name.lower() in SECRET_NAMES for name in request_context):
            raise BronzeStorageError("Bronze request_context contains an API key field.")
        try:
            return json.dumps(
                record, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise BronzeStorageError("Bronze record is not JSON serializable.") from error

    @staticmethod
    def object_name(record: dict[str, Any], content: bytes) -> str:
        run_id = str(record["run_id"])
        resource = str(record["resource"])
        if not run_id or "/" in run_id or not resource or "/" in resource:
            raise BronzeStorageError("Invalid run_id or resource for Bronze path.")
        object_id = sha256(content).hexdigest()
        return f"bronze/youtube/{resource}/run_id={run_id}/{object_id}.json"

    @staticmethod
    def _is_missing_object(error: Exception) -> bool:
        return getattr(error, "code", None) in {
            "NoSuchKey",
            "NoSuchObject",
            "NotFound",
        }

    def _read_bytes(self, object_name: str) -> bytes:
        response = self.client.get_object(self.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def write_record(self, record: dict[str, Any]) -> str:
        content = self.serialize_record(record)
        object_name = self.object_name(record, content)

        try:
            existing = self._read_bytes(object_name)
        except Exception as error:
            if not self._is_missing_object(error):
                raise BronzeStorageError(
                    f"Unable to check Bronze object {object_name}."
                ) from error
        else:
            if existing == content:
                return object_name
            raise BronzeStorageError(
                f"Bronze object already exists with different content: {object_name}."
            )

        try:
            self.client.put_object(
                self.bucket,
                object_name,
                BytesIO(content),
                len(content),
                content_type="application/json",
            )
        except Exception as error:
            raise BronzeStorageError(
                f"Unable to write Bronze object {object_name}."
            ) from error
        return object_name

    def read_record(self, object_name: str) -> dict[str, Any]:
        try:
            content = self._read_bytes(object_name)
            record = json.loads(content)
        except Exception as error:
            raise BronzeStorageError(
                f"Unable to read Bronze object {object_name}."
            ) from error
        if not isinstance(record, dict):
            raise BronzeStorageError(f"Invalid Bronze object {object_name}.")
        return record
