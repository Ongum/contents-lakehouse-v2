"""Small GCS client adapter for the existing Bronze storage contracts."""

import os
from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace
from typing import Any


class GCSStorageError(Exception):
    """Raised when GCS configuration or access cannot be prepared."""


class GCSObjectError(Exception):
    """Expose storage error codes expected by the existing storage classes."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GCSSettings:
    project_id: str
    bucket: str

    @classmethod
    def from_environment(cls) -> "GCSSettings":
        project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
        bucket = (
            os.environ.get("GCS_BUCKET", "").strip()
            or os.environ.get("GCS_BRONZE_BUCKET", "").strip()
        )
        missing = [
            name
            for name, value in (
                ("GCP_PROJECT_ID", project_id),
                ("GCS_BUCKET", bucket),
            )
            if not value
        ]
        if missing:
            raise GCSStorageError(
                f"Missing GCS configuration: {', '.join(missing)}."
            )
        return cls(project_id=project_id, bucket=bucket)


class _GCSResponse:
    def __init__(self, content: bytes) -> None:
        self._stream = BytesIO(content)

    def read(self) -> bytes:
        return self._stream.read()

    def close(self) -> None:
        self._stream.close()

    def release_conn(self) -> None:
        return None


class GCSClientAdapter:
    """Present the narrow MinIO-client surface used by Bronze persistence."""

    def __init__(self, client: Any, project_id: str) -> None:
        self.client = client
        self.project_id = project_id

    @classmethod
    def from_environment(cls) -> tuple["GCSClientAdapter", str]:
        settings = GCSSettings.from_environment()
        try:
            from google.cloud import storage
        except ImportError as error:
            raise GCSStorageError(
                "GCS client is not installed. Run: pip install -r requirements.txt"
            ) from error
        return cls(storage.Client(project=settings.project_id), settings.project_id), settings.bucket

    def bucket_exists(self, bucket: str) -> bool:
        """Assume a pre-provisioned bucket; object operations validate access."""
        return True

    def make_bucket(self, bucket: str) -> None:
        raise GCSStorageError(
            f"GCS bucket {bucket} does not exist or is not accessible; "
            "the GCS backend requires a pre-provisioned bucket."
        )

    def get_object(self, bucket: str, object_name: str) -> _GCSResponse:
        blob = self.client.bucket(bucket).blob(object_name)
        try:
            return _GCSResponse(blob.download_as_bytes())
        except Exception as error:
            if getattr(error, "code", None) == 404:
                raise GCSObjectError(f"GCS object not found: {object_name}.", "NotFound") from error
            raise

    def put_object(
        self,
        bucket: str,
        object_name: str,
        data: Any,
        length: int,
        content_type: str | None = None,
    ) -> None:
        content = data.read(length)
        self._create_object(bucket, object_name, content, content_type)

    def list_objects(self, bucket: str, prefix: str, recursive: bool = True) -> Any:
        del recursive
        return (
            SimpleNamespace(object_name=blob.name)
            for blob in self.client.list_blobs(bucket, prefix=prefix)
        )

    def _put_object(
        self,
        bucket: str,
        object_name: str,
        content: bytes,
        headers: dict[str, str],
    ) -> None:
        """Atomically create an advertising object using a GCS generation guard."""
        self._create_object(
            bucket, object_name, content, headers.get("Content-Type")
        )

    def _create_object(
        self,
        bucket: str,
        object_name: str,
        content: bytes,
        content_type: str | None,
    ) -> None:
        try:
            self.client.bucket(bucket).blob(object_name).upload_from_string(
                content,
                content_type=content_type,
                if_generation_match=0,
            )
        except Exception as error:
            if getattr(error, "code", None) in {409, 412}:
                raise GCSObjectError(
                    f"GCS object already exists: {object_name}.",
                    "PreconditionFailed",
                ) from error
            raise
