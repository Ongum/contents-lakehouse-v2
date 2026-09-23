import json
import base64
import socket
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError

from src.advertising_bronze_storage import AdvertisingBronzeStorage
from src.advertising_collection import (
    CollectionStatus,
    FetchedDocument,
    SourceConfig,
    build_bronze_record,
    canonicalize_content,
    collect_source,
    content_hash,
    is_sensitive_name,
    sanitize_metadata,
    safe_url,
)
from src.http_document_adapter import HttpDocumentAdapter


class MissingObjectError(Exception):
    code = "NoSuchKey"


class PreconditionFailedError(Exception):
    code = "PreconditionFailed"


class FakeStoredResponse:
    def __init__(self, content):
        self.content = content

    def read(self):
        return self.content

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeHttpResponse:
    def __init__(self, body=b"document", content_type="text/plain; charset=utf-8"):
        self.body = body
        self.status = 200
        self.headers = {"Content-Type": content_type, "ETag": '"v1"'}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]

    def getcode(self):
        return self.status

    def geturl(self):
        return "https://example.test/document"


class FakeMinioClient:
    def __init__(self):
        self.objects = {}
        self.put_count = 0

    def get_object(self, bucket, object_name):
        try:
            return FakeStoredResponse(self.objects[(bucket, object_name)])
        except KeyError as error:
            raise MissingObjectError() from error

    def _put_object(self, bucket, object_name, data, headers):
        self.last_put_headers = headers
        key = (bucket, object_name)
        if key in self.objects and headers.get("If-None-Match") == "*":
            raise PreconditionFailedError()
        self.put_count += 1
        self.objects[key] = data

    def list_objects(self, bucket, prefix, recursive):
        return [
            type("Object", (), {"object_name": object_name})()
            for stored_bucket, object_name in self.objects
            if stored_bucket == bucket and object_name.startswith(prefix)
        ]


class StaticAdapter:
    def __init__(self, content):
        self.content = canonicalize_content(content)
        self.last_attempts = 1

    def fetch(self, _config):
        raw_bytes = self.content.encode("utf-8")
        return FetchedDocument(
            self.content,
            content_hash(self.content),
            {"method": "GET", "request_headers": {"Accept": "text/plain"}},
            base64.b64encode(raw_bytes).decode("ascii"),
            __import__("hashlib").sha256(raw_bytes).hexdigest(),
            content_hash(self.content),
        )


def config():
    return SourceConfig(
        source_type="official_company_page",
        source_name="Narangd source",
        source_url="https://example.test/news?id=672",
        source_identifier="company:news:672",
        published_at="2026-08-27",
        respect_robots=False,
    )


class AdvertisingBronzeTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeMinioClient()
        self.storage = AdvertisingBronzeStorage(self.client, "lakehouse")

    def test_content_hash_is_deterministic_and_normalizes_newlines(self):
        self.assertEqual(content_hash("a\r\nb"), content_hash("a\nb"))

    def test_retrieved_at_does_not_affect_content_identity_or_object_key(self):
        document = StaticAdapter("same").fetch(config())
        first = build_bronze_record(config(), document, "run-1", "2026-01-01Z", None)
        second = build_bronze_record(config(), document, "run-2", "2026-01-02Z", None)

        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(
            self.storage.object_name(first), self.storage.object_name(second)
        )

    def test_same_content_becomes_unchanged(self):
        first = collect_source(config(), StaticAdapter("same"), self.storage)
        second = collect_source(config(), StaticAdapter("same"), self.storage)

        self.assertEqual(first.status, CollectionStatus.SUCCESS)
        self.assertEqual(second.status, CollectionStatus.UNCHANGED)
        self.assertEqual(first.object_key, second.object_key)
        self.assertEqual(self.client.put_count, 1)

    def test_changed_content_creates_new_version(self):
        first = collect_source(config(), StaticAdapter("first"), self.storage)
        second = collect_source(config(), StaticAdapter("second"), self.storage)

        self.assertEqual(second.status, CollectionStatus.SUCCESS)
        self.assertNotEqual(first.object_key, second.object_key)
        self.assertTrue(second.content_changed)
        self.assertEqual(second.record["previous_content_hash"], first.content_hash)
        self.assertEqual(self.client.put_count, 2)

    def test_object_key_is_deterministic_and_does_not_embed_url(self):
        result = collect_source(config(), StaticAdapter("same"), self.storage)

        self.assertRegex(
            result.object_key,
            r"^bronze/advertising/official_company_page/"
            r"source_id=[0-9a-f]{64}/content_hash=[0-9a-f]{64}/document.json$",
        )
        self.assertNotIn("example.test", result.object_key)
        self.assertNotIn("?", result.object_key)

    def test_timeout_is_retried_and_classified_retryable(self):
        calls = []

        def timeout_opener(*_args, **_kwargs):
            calls.append(True)
            raise URLError(socket.timeout("timed out"))

        adapter = HttpDocumentAdapter(opener=timeout_opener, sleeper=lambda _: None)
        result = collect_source(config(), adapter, self.storage)

        self.assertEqual(result.status, CollectionStatus.RETRYABLE_FAILURE)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(len(calls), 3)

    def test_permanent_http_error_is_not_retried(self):
        calls = []

        def not_found(*_args, **_kwargs):
            calls.append(True)
            raise HTTPError("https://example.test", 404, "missing", {}, None)

        adapter = HttpDocumentAdapter(opener=not_found, sleeper=lambda _: None)
        result = collect_source(config(), adapter, self.storage)

        self.assertEqual(result.status, CollectionStatus.PERMANENT_FAILURE)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(calls), 1)

    def test_robots_disallow_is_a_permanent_failure(self):
        calls = []

        def robots_opener(request, **_kwargs):
            calls.append(request.full_url)
            return FakeHttpResponse(b"User-agent: *\nDisallow: /document")

        adapter = HttpDocumentAdapter(opener=robots_opener, sleeper=lambda _: None)
        restricted = SourceConfig(
            source_type="official_company_page",
            source_name="Restricted source",
            source_url="https://example.test/document",
            source_identifier="restricted:1",
        )

        result = collect_source(restricted, adapter, self.storage)

        self.assertEqual(result.status, CollectionStatus.PERMANENT_FAILURE)
        self.assertEqual(calls, ["https://example.test/robots.txt"])

    def test_request_metadata_excludes_secrets(self):
        metadata = sanitize_metadata(
            {
                "method": "GET",
                "request_headers": {
                    "Accept": "text/plain",
                    "Authorization": "secret",
                    "Cookie": "secret",
                },
                "token": "secret",
            }
        )
        serialized = json.dumps(metadata)

        self.assertNotIn("secret", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("Cookie", serialized)

    def test_common_credential_name_variants_are_detected(self):
        for name in (
            "api_key",
            "apiKey",
            "X-API-Key",
            "ACCESS_TOKEN",
            "auth-token",
            "client_secret",
            "Authorization",
            "cookie",
            "Set-Cookie",
            "password",
            "PASSWD",
            "signature",
            "sig",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_sensitive_name(name))
                sanitized = sanitize_metadata({name: "do-not-persist"})
                self.assertNotIn("do-not-persist", json.dumps(sanitized))

    def test_ordinary_metadata_names_are_not_redacted(self):
        metadata = {
            "monkey": "animal",
            "keyboard_layout": "qwerty",
            "tokenization_method": "unicode",
            "signature_algorithm_name": "sha256-description",
        }

        self.assertEqual(sanitize_metadata(metadata), metadata)

    def test_safe_url_redacts_credential_query_variants(self):
        safe = safe_url(
            "https://example.test/data?access-token=secret&apiKey=hidden&category=drink"
        )

        self.assertNotIn("secret", safe)
        self.assertNotIn("hidden", safe)
        self.assertIn("category=drink", safe)

    def test_existing_conflicting_content_is_never_overwritten(self):
        document = StaticAdapter("expected").fetch(config())
        record = build_bronze_record(config(), document, "run-1", "2026-01-01Z", None)
        object_name = self.storage.object_name(record)
        conflicting = dict(record, raw_content="different")
        self.client.objects[("lakehouse", object_name)] = json.dumps(
            conflicting
        ).encode()

        before = self.client.objects[("lakehouse", object_name)]
        result = collect_source(config(), StaticAdapter("expected"), self.storage)

        self.assertEqual(result.status, CollectionStatus.QUARANTINED)
        self.assertEqual(result.error_type, "storage_conflict")
        self.assertEqual(self.client.objects[("lakehouse", object_name)], before)

    def test_equivalent_existing_conditional_write_is_unchanged(self):
        first = collect_source(config(), StaticAdapter("same"), self.storage)
        before = self.client.objects[("lakehouse", first.object_key)]

        second = collect_source(config(), StaticAdapter("same"), self.storage)

        self.assertEqual(second.status, CollectionStatus.UNCHANGED)
        self.assertEqual(self.client.objects[("lakehouse", first.object_key)], before)

    def test_storage_uses_atomic_create_only_precondition(self):
        result = collect_source(config(), StaticAdapter("same"), self.storage)

        self.assertEqual(result.status, CollectionStatus.SUCCESS)
        self.assertEqual(self.client.last_put_headers["If-None-Match"], "*")

    def test_malformed_response_is_quarantined(self):
        adapter = HttpDocumentAdapter(
            opener=lambda *_args, **_kwargs: FakeHttpResponse(
                b"binary", "application/octet-stream"
            ),
            sleeper=lambda _: None,
        )
        result = collect_source(config(), adapter, self.storage)

        self.assertEqual(result.status, CollectionStatus.QUARANTINED)
        self.assertEqual(result.error_type, "malformed_response")

    def test_euc_kr_declaration_can_use_deterministic_cp949_fallback(self):
        text = "나랑드사이다 똠 리센느"
        adapter = HttpDocumentAdapter(
            opener=lambda *_args, **_kwargs: FakeHttpResponse(
                text.encode("cp949"), "text/html; charset=euc-kr"
            ),
            sleeper=lambda _: None,
        )

        result = collect_source(config(), adapter, self.storage)

        self.assertEqual(result.status, CollectionStatus.SUCCESS)
        self.assertEqual(result.record["raw_content"], text)
        self.assertEqual(
            result.record["request_metadata"]["response"]["charset"], "cp949"
        )

    def test_malformed_cp949_preserves_exact_source_bytes(self):
        body = "리센느".encode("cp949") + b"\x81"
        adapter = HttpDocumentAdapter(
            opener=lambda *_args, **_kwargs: FakeHttpResponse(
                body, "text/html; charset=euc-kr"
            ),
            sleeper=lambda _: None,
        )

        result = collect_source(config(), adapter, self.storage)

        self.assertEqual(result.status, CollectionStatus.SUCCESS)
        self.assertEqual(
            base64.b64decode(result.record["raw_content_bytes_base64"]), body
        )
        self.assertEqual(
            result.record["request_metadata"]["response"][
                "decode_replacement_count"
            ],
            1,
        )

    def test_donga_adapter_ignores_view_counter_for_content_identity(self):
        bodies = iter(
            [
                '<th class="bdl">조회</th><td>164</td>본문'.encode(),
                '<th class="bdl">조회</th><td>165</td>본문'.encode(),
            ]
        )
        def without_view_count(content):
            return (
                __import__("re").sub(r"(<td>)\d+(</td>)", r"\1{view}\2", content),
                "test_without_view_count_v1",
            )

        adapter = HttpDocumentAdapter(
            opener=lambda *_args, **_kwargs: FakeHttpResponse(next(bodies)),
            sleeper=lambda _: None,
            identity_canonicalizer=without_view_count,
        )

        first = collect_source(config(), adapter, self.storage)
        second = collect_source(config(), adapter, self.storage)

        self.assertEqual(first.status, CollectionStatus.SUCCESS)
        self.assertEqual(second.status, CollectionStatus.UNCHANGED)
        self.assertNotEqual(
            first.record["raw_content_bytes_hash"],
            __import__("hashlib").sha256(
                '<th class="bdl">조회</th><td>165</td>본문'.encode()
            ).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
