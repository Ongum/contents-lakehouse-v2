import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bronze_storage import BronzeStorage, BronzeStorageError
from gcs_storage import GCSClientAdapter, GCSObjectError, GCSSettings
from mediawiki_bronze import MediaWikiBronzeStorage, build_bronze_record, parse_latest_revision
from storage_factory import bronze_storage_from_environment


class _Blob:
    def __init__(
        self, name: str, objects: dict[str, bytes], preconditions: list[int | None]
    ) -> None:
        self.name = name
        self.objects = objects
        self.preconditions = preconditions

    def download_as_bytes(self) -> bytes:
        if self.name not in self.objects:
            error = RuntimeError("missing")
            error.code = 404
            raise error
        return self.objects[self.name]

    def upload_from_string(
        self,
        content: bytes,
        content_type: str | None = None,
        if_generation_match: int | None = None,
    ) -> None:
        del content_type
        self.preconditions.append(if_generation_match)
        if if_generation_match == 0 and self.name in self.objects:
            error = RuntimeError("precondition")
            error.code = 412
            raise error
        self.objects[self.name] = content


class _Bucket:
    def __init__(self, client: "_Client") -> None:
        self.client = client
        self.objects = client.objects

    def exists(self, client=None) -> bool:
        del client
        return self.client.bucket_accessible

    def blob(self, name: str) -> _Blob:
        return _Blob(name, self.objects, self.client.preconditions)


class _Client:
    def __init__(self, bucket_accessible: bool = True) -> None:
        self.objects: dict[str, bytes] = {}
        self.bucket_accessible = bucket_accessible
        self.create_bucket_calls = 0
        self.preconditions: list[int | None] = []

    def bucket(self, name: str) -> _Bucket:
        del name
        return _Bucket(self)

    def create_bucket(self, name: str, project: str) -> None:
        del name, project
        self.create_bucket_calls += 1

    def list_blobs(self, bucket: str, prefix: str):
        del bucket
        return [
            _Blob(name, self.objects, self.preconditions)
            for name in self.objects
            if name.startswith(prefix)
        ]


class GCSStorageTest(unittest.TestCase):
    def test_settings_require_project_and_bucket(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(Exception, "GCP_PROJECT_ID"):
                GCSSettings.from_environment()

    def test_primary_bucket_setting_is_preferred(self) -> None:
        environment = {
            "GCP_PROJECT_ID": "fandom-data-lakehouse",
            "GCS_BUCKET": "primary",
            "GCS_BRONZE_BUCKET": "legacy",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(GCSSettings.from_environment().bucket, "primary")

    def test_legacy_bucket_setting_remains_supported(self) -> None:
        environment = {
            "GCP_PROJECT_ID": "fandom-data-lakehouse",
            "GCS_BRONZE_BUCKET": "legacy",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(GCSSettings.from_environment().bucket, "legacy")

    def test_missing_gcs_bucket_is_not_created(self) -> None:
        client = _Client(bucket_accessible=False)
        storage = BronzeStorage(GCSClientAdapter(client, "project"), "missing")

        with self.assertRaisesRegex(BronzeStorageError, "pre-provisioned bucket"):
            storage.ensure_bucket()

        self.assertEqual(client.create_bucket_calls, 0)

    def test_adapter_supports_existing_bronze_storage_contract(self) -> None:
        client = _Client()
        storage = BronzeStorage(GCSClientAdapter(client, "project"), "bucket")
        record = {
            "run_id": "run-1",
            "source": "youtube",
            "resource": "videos",
            "observed_at": "2026-01-01T00:00:00Z",
            "ingested_at": "2026-01-01T00:00:01Z",
            "request_context": {},
            "raw_payload": {"items": []},
        }
        object_name = storage.write_record(record)
        self.assertEqual(storage.read_record(object_name), record)
        self.assertEqual(storage.write_record(record), object_name)

    def test_atomic_create_maps_gcs_precondition(self) -> None:
        client = _Client()
        adapter = GCSClientAdapter(client, "project")
        adapter._put_object("bucket", "object", b"first", {"Content-Type": "text/plain"})
        with self.assertRaises(GCSObjectError) as raised:
            adapter._put_object(
                "bucket", "object", b"second", {"Content-Type": "text/plain"}
            )
        self.assertEqual(raised.exception.code, "PreconditionFailed")
        self.assertEqual(client.objects["object"], b"first")

    def test_mediawiki_gcs_write_is_create_only_and_idempotent(self) -> None:
        client = _Client()
        storage = MediaWikiBronzeStorage(
            GCSClientAdapter(client, "project"), "bucket"
        )
        revision = parse_latest_revision(
            {
                "query": {
                    "pages": [{
                        "pageid": 76400327,
                        "title": "Rescene",
                        "revisions": [{
                            "revid": 1376088055,
                            "parentid": 1376088054,
                            "timestamp": "2026-09-22T00:27:05Z",
                            "slots": {"main": {"content": "{{Infobox}}"}},
                        }],
                    }]
                }
            }
        )
        first = build_bronze_record(revision, "2026-09-23T10:00:00Z")
        second = build_bronze_record(revision, "2026-09-23T11:00:00Z")

        object_name, created = storage.write_record(first)
        same_name, second_created = storage.write_record(second)

        self.assertTrue(created)
        self.assertFalse(second_created)
        self.assertEqual(same_name, object_name)
        self.assertEqual(storage.read_record(object_name), first)
        self.assertEqual(client.preconditions, [0])

    def test_factory_defaults_to_existing_minio_path(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            BronzeStorage, "from_environment", return_value="minio"
        ):
            self.assertEqual(
                bronze_storage_from_environment(BronzeStorage), "minio"
            )

    def test_factory_rejects_unknown_backend(self) -> None:
        with patch.dict(os.environ, {"BRONZE_STORAGE_BACKEND": "unknown"}):
            with self.assertRaises(BronzeStorageError):
                bronze_storage_from_environment(BronzeStorage)


if __name__ == "__main__":
    unittest.main()
