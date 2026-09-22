import unittest

from src.bronze_storage import BronzeStorage, BronzeStorageError


class MissingObjectError(Exception):
    code = "NoSuchKey"


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def read(self):
        return self.content

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeObject:
    def __init__(self, object_name):
        self.object_name = object_name


class FakeMinioClient:
    def __init__(self):
        self.bucket_created = False
        self.objects = {}
        self.put_count = 0
        self.put_error = None

    def bucket_exists(self, _bucket):
        return self.bucket_created

    def make_bucket(self, _bucket):
        self.bucket_created = True

    def get_object(self, bucket, object_name):
        try:
            return FakeResponse(self.objects[(bucket, object_name)])
        except KeyError as error:
            raise MissingObjectError() from error

    def put_object(self, bucket, object_name, data, length, content_type):
        if self.put_error:
            raise self.put_error
        self.put_count += 1
        self.objects[(bucket, object_name)] = data.read(length)

    def list_objects(self, bucket, prefix, recursive):
        return [
            FakeObject(object_name)
            for stored_bucket, object_name in self.objects
            if stored_bucket == bucket and object_name.startswith(prefix)
        ]


def bronze_record():
    return {
        "run_id": "run-123",
        "source": "youtube",
        "resource": "videos",
        "observed_at": "2026-09-22T11:59:00Z",
        "ingested_at": "2026-09-22T12:00:00Z",
        "request_context": {"part": "snippet,statistics", "id": "video-1"},
        "raw_payload": {"items": [{"id": "video-1", "unchanged": [1, 2]}]},
    }


class BronzeStorageTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeMinioClient()
        self.storage = BronzeStorage(self.client, "lakehouse")
        self.storage.ensure_bucket()

    def test_write_and_read_preserves_record_at_api_response_grain(self):
        record = bronze_record()
        object_name = self.storage.write_record(record)

        self.assertTrue(
            object_name.startswith("bronze/youtube/videos/run_id=run-123/")
        )
        self.assertEqual(self.storage.read_record(object_name), record)
        self.assertEqual(self.client.put_count, 1)

    def test_retry_does_not_overwrite_identical_object(self):
        record = bronze_record()
        first_name = self.storage.write_record(record)
        second_name = self.storage.write_record(record)

        self.assertEqual(first_name, second_name)
        self.assertEqual(self.client.put_count, 1)

    def test_lists_persisted_bronze_records_with_source_reference(self):
        record = bronze_record()
        object_name = self.storage.write_record(record)

        self.assertEqual(
            self.storage.list_records(),
            [(object_name, record)],
        )

    def test_api_key_field_is_rejected(self):
        record = bronze_record()
        record["request_context"]["key"] = "secret"

        with self.assertRaisesRegex(BronzeStorageError, "API key"):
            self.storage.write_record(record)

    def test_write_failure_is_reported(self):
        self.client.put_error = OSError("MinIO unavailable")

        with self.assertRaisesRegex(BronzeStorageError, "Unable to write"):
            self.storage.write_record(bronze_record())


if __name__ == "__main__":
    unittest.main()
