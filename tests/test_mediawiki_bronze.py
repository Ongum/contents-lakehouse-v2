import io
import json
import unittest
from unittest.mock import patch

from src.bronze_storage import BronzeStorageError
from src.mediawiki_bronze import (
    MediaWikiBronzeStorage,
    build_bronze_record,
    fetch_latest_revision,
    parse_latest_revision,
)


class MissingObjectError(Exception):
    code = "NoSuchKey"


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return io.BytesIO(self.body)

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeStoredResponse:
    def __init__(self, content):
        self.content = content

    def read(self):
        return self.content

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeMinioClient:
    def __init__(self):
        self.objects = {}
        self.put_count = 0

    def get_object(self, bucket, object_name):
        try:
            return FakeStoredResponse(self.objects[(bucket, object_name)])
        except KeyError as error:
            raise MissingObjectError() from error

    def put_object(self, bucket, object_name, data, length, content_type):
        self.put_count += 1
        self.objects[(bucket, object_name)] = data.read(length)


def api_payload(revision_id=1376088055, wikitext="{{Infobox}}"):
    return {
        "batchcomplete": True,
        "query": {
            "pages": [
                {
                    "pageid": 76400327,
                    "ns": 0,
                    "title": "Rescene",
                    "revisions": [
                        {
                            "revid": revision_id,
                            "parentid": revision_id - 1,
                            "timestamp": "2026-09-22T00:27:05Z",
                            "slots": {
                                "main": {
                                    "contentmodel": "wikitext",
                                    "contentformat": "text/x-wiki",
                                    "content": wikitext,
                                }
                            },
                        }
                    ],
                }
            ]
        },
    }


class MediaWikiBronzeTest(unittest.TestCase):
    @patch(
        "src.mediawiki_bronze.urlopen",
        return_value=FakeResponse(api_payload()),
    )
    def test_fetch_uses_action_api_and_no_authentication(self, urlopen_mock):
        self.assertEqual(fetch_latest_revision(), api_payload())

        request = urlopen_mock.call_args.args[0]
        self.assertIn("action=query", request.full_url)
        self.assertIn("titles=Rescene", request.full_url)
        self.assertNotIn("token", request.full_url.lower())
        self.assertNotIn("key", request.full_url.lower())

    def test_parses_revision_metadata_and_raw_wikitext(self):
        parsed = parse_latest_revision(api_payload(wikitext="raw {{content}}"))

        self.assertEqual(parsed["page_id"], 76400327)
        self.assertEqual(parsed["canonical_title"], "Rescene")
        self.assertEqual(parsed["revision_id"], 1376088055)
        self.assertEqual(parsed["parent_revision_id"], 1376088054)
        self.assertEqual(parsed["revision_timestamp"], "2026-09-22T00:27:05Z")
        self.assertEqual(parsed["raw_wikitext"], "raw {{content}}")

    def test_builds_bronze_record_with_separate_ingestion_time(self):
        revision = parse_latest_revision(api_payload())
        record = build_bronze_record(revision, "2026-09-23T10:00:00Z")

        self.assertEqual(record["source"], "mediawiki")
        self.assertEqual(record["edition"], "en")
        self.assertEqual(record["revision_timestamp"], "2026-09-22T00:27:05Z")
        self.assertEqual(record["ingested_at"], "2026-09-23T10:00:00Z")
        self.assertEqual(record["raw_wikitext"], "{{Infobox}}")

    def test_same_revision_is_stored_once_even_with_new_ingestion_time(self):
        client = FakeMinioClient()
        storage = MediaWikiBronzeStorage(client, "lakehouse")
        revision = parse_latest_revision(api_payload())
        first = build_bronze_record(revision, "2026-09-23T10:00:00Z")
        second = build_bronze_record(revision, "2026-09-23T11:00:00Z")

        first_name, first_created = storage.write_record(first)
        second_name, second_created = storage.write_record(second)

        self.assertEqual(first_name, second_name)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(client.put_count, 1)
        self.assertEqual(storage.read_record(first_name), first)

    def test_different_revisions_coexist(self):
        client = FakeMinioClient()
        storage = MediaWikiBronzeStorage(client, "lakehouse")
        first = build_bronze_record(parse_latest_revision(api_payload()))
        second = build_bronze_record(
            parse_latest_revision(api_payload(revision_id=1376088056))
        )

        first_name, _ = storage.write_record(first)
        second_name, _ = storage.write_record(second)

        self.assertNotEqual(first_name, second_name)
        self.assertEqual(client.put_count, 2)
        self.assertIn("revision_id=1376088055", first_name)
        self.assertIn("revision_id=1376088056", second_name)

    def test_existing_conflicting_identity_is_not_overwritten(self):
        client = FakeMinioClient()
        storage = MediaWikiBronzeStorage(client, "lakehouse")
        record = build_bronze_record(parse_latest_revision(api_payload()))
        object_name = storage.object_name(record)
        conflicting = dict(record, source="other")
        client.objects[("lakehouse", object_name)] = json.dumps(conflicting).encode()

        with self.assertRaisesRegex(BronzeStorageError, "conflicting identity"):
            storage.write_record(record)
        self.assertEqual(client.put_count, 0)


if __name__ == "__main__":
    unittest.main()
