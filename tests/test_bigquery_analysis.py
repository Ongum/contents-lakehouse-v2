import tempfile
import unittest
from pathlib import Path

from src.bigquery_analysis import (
    BigQueryAnalysisError,
    build_snapshot_plan,
    default_snapshot_id,
    load_eda_manifest,
    render_bigquery_ddl,
)
from src.bigquery_snapshot import publish_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
BUCKET = "fandom-data-lakehouse-bronze"
PROJECT = "fandom-data-lakehouse"
DATASET = "contents_lakehouse"


class FakeBlob:
    def __init__(self, name, exists=False, md5_hash=None, crc32c=None):
        self.name = name
        self._exists = exists
        self.md5_hash = md5_hash
        self.crc32c = crc32c
        self.uploaded = False

    def exists(self, client=None):
        del client
        return self._exists

    def reload(self):
        return None

    def upload_from_filename(self, *args, **kwargs):
        del args, kwargs
        self.uploaded = True

    def upload_from_string(self, *args, **kwargs):
        del args, kwargs
        self.uploaded = True


class FakeBucket:
    def __init__(self):
        self.blobs = {}
        self.copied = False

    def blob(self, name):
        return self.blobs.setdefault(name, FakeBlob(name))

    def copy_blob(self, *args, **kwargs):
        del args, kwargs
        self.copied = True


class FakeStorageClient:
    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self.fake_bucket = FakeBucket()

    def bucket(self, name):
        assert name == self.bucket_name
        return self.fake_bucket


class BigQueryAnalysisTest(unittest.TestCase):
    def setUp(self):
        manifest = load_eda_manifest(REPO_ROOT)
        self.snapshot_id = default_snapshot_id(manifest["exported_at_utc"])
        self.plan = build_snapshot_plan(REPO_ROOT, BUCKET, self.snapshot_id)

    def test_snapshot_plan_covers_all_19_analysis_tables(self):
        tables = {item.table for item in self.plan}
        self.assertEqual(len(tables), 19)
        self.assertIn("youtube_video", tables)
        self.assertIn("video_metrics_snapshot", tables)
        self.assertIn("artist_activity", tables)
        self.assertEqual(
            {item.source_kind for item in self.plan if item.table == "artist_activity"},
            {"gcs"},
        )
        self.assertTrue(
            all(f"snapshot_id={self.snapshot_id}" in item.destination for item in self.plan)
        )

    def test_ddl_creates_external_table_and_view_per_table(self):
        ddl = render_bigquery_ddl(
            self.plan, PROJECT, DATASET, BUCKET, self.snapshot_id
        )
        self.assertEqual(ddl.count("CREATE OR REPLACE EXTERNAL TABLE"), 19)
        self.assertEqual(ddl.count("CREATE OR REPLACE VIEW"), 19)
        self.assertIn("`fandom-data-lakehouse.contents_lakehouse.artist`", ddl)
        self.assertIn(
            "silver/analysis_snapshots/"
            f"snapshot_id={self.snapshot_id}/artist/*.parquet",
            ddl,
        )

    def test_youtube_tags_are_normalized_in_logical_view(self):
        ddl = render_bigquery_ddl(
            self.plan, PROJECT, DATASET, BUCKET, self.snapshot_id
        )
        self.assertIn("UNNEST(tags.list) AS item", ddl)
        self.assertIn("END AS tags", ddl)

    def test_invalid_identifier_is_rejected(self):
        with self.assertRaises(BigQueryAnalysisError):
            render_bigquery_ddl(
                self.plan,
                PROJECT,
                "bad.dataset",
                BUCKET,
                self.snapshot_id,
            )

    def test_snapshot_publication_defaults_to_read_only_plan(self):
        client = FakeStorageClient(BUCKET)
        live = client.fake_bucket.blob("silver/artist_activity/artist_activity.parquet")
        live._exists = True
        live.md5_hash = "source-md5"
        actions = publish_snapshot(self.plan, BUCKET, client, apply=False)
        self.assertEqual(len(actions), len(self.plan) + 1)
        self.assertTrue(
            all(action["action"].startswith("would_") for action in actions)
        )
        self.assertFalse(client.fake_bucket.copied)
        self.assertFalse(any(blob.uploaded for blob in client.fake_bucket.blobs.values()))

    def test_manifest_without_parquet_fails_before_cloud_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_dir = root / "data" / "eda" / "youtube_september_2026"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "manifest.json").write_text(
                '{"contract_version":1,"exported_at_utc":"2026-01-01T00:00:00Z",'
                '"tables":[{"source_table":"lakehouse.silver.missing",'
                '"output":"missing.parquet","row_count":0,"columns":["id"]}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BigQueryAnalysisError, "No Parquet data"):
                build_snapshot_plan(root, BUCKET, "20260101T000000Z")


if __name__ == "__main__":
    unittest.main()
