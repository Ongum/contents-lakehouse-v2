import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from advertising_collection import CollectionStatus
import run_advertising_pipeline
import run_mediawiki_pipeline
import run_youtube_pipeline


def events(output):
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


class FakeSpark:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class PipelineEntrypointTest(unittest.TestCase):
    def test_youtube_success_returns_zero_and_passes_one_run_context(self):
        output = io.StringIO()
        with patch.object(
            run_youtube_pipeline, "run_existing_youtube_pipeline", return_value=0
        ) as existing, redirect_stdout(output):
            code = run_youtube_pipeline.main()

        self.assertEqual(code, 0)
        self.assertIsNotNone(existing.call_args.kwargs["run_id"])
        self.assertTrue(existing.call_args.kwargs["observed_at"].endswith("Z"))
        self.assertEqual(events(output.getvalue())[-1]["status"], "SUCCEEDED")

    def test_failure_returns_nonzero_and_redacts_credentials(self):
        error = io.StringIO()
        output = io.StringIO()
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": "super-secret-key"}), patch.object(
            run_youtube_pipeline,
            "run_existing_youtube_pipeline",
            side_effect=RuntimeError("failed with super-secret-key"),
        ), redirect_stdout(output), redirect_stderr(error):
            code = run_youtube_pipeline.main()

        self.assertEqual(code, 1)
        self.assertNotIn("super-secret-key", error.getvalue())
        failure = events(error.getvalue())[-1]
        self.assertEqual(failure["status"], "FAILED")
        self.assertEqual(failure["error_type"], "RuntimeError")

    def test_mediawiki_stages_execute_in_order(self):
        output = io.StringIO()
        storage = Mock()
        storage_type = Mock()
        storage_type.from_environment.return_value = storage
        result = SimpleNamespace(
            invalid_records=[],
            artists=[{}],
            artist_relationships=[{}],
            artist_events=[{}],
        )
        spark = FakeSpark()
        with patch.object(run_mediawiki_pipeline, "MediaWikiBronzeStorage", storage_type), patch.object(
            run_mediawiki_pipeline,
            "ingest_latest_revision",
            return_value=("bronze/object", False, {"revision_id": 1}),
        ), patch.object(
            run_mediawiki_pipeline, "transform_mediawiki_bronze", return_value=result
        ), patch.object(
            run_mediawiki_pipeline, "build_spark_session", return_value=spark
        ), patch.object(
            run_mediawiki_pipeline, "persist_mediawiki_silver_result"
        ), redirect_stdout(output):
            code = run_mediawiki_pipeline.main()

        self.assertEqual(code, 0)
        started = [x["stage"] for x in events(output.getvalue()) if x["status"] == "STARTED"]
        self.assertEqual(
            started,
            ["pipeline", "bronze_collection", "silver_transformation", "silver_iceberg"],
        )
        self.assertTrue(spark.stopped)

    def test_advertising_stages_execute_in_order(self):
        output = io.StringIO()
        storage = Mock()
        storage.read_record.return_value = {}
        storage_type = Mock()
        storage_type.from_environment.return_value = storage
        collected = SimpleNamespace(
            status=CollectionStatus.UNCHANGED,
            object_key="bronze/object",
            error_message=None,
            content_created=False,
            record={},
        )
        transformed = SimpleNamespace(
            invalid_records=[], organizations=[{}], campaigns=[{}], market_metrics=[]
        )
        spark = FakeSpark()
        with patch.object(run_advertising_pipeline, "AdvertisingBronzeStorage", storage_type), patch.object(
            run_advertising_pipeline, "collect_source", return_value=collected
        ), patch.object(
            run_advertising_pipeline,
            "transform_advertising_bronze",
            return_value=transformed,
        ), patch.object(
            run_advertising_pipeline, "build_spark_session", return_value=spark
        ), patch.object(
            run_advertising_pipeline, "persist_advertising_silver_result"
        ), redirect_stdout(output):
            code = run_advertising_pipeline.main()

        self.assertEqual(code, 0)
        started = [x["stage"] for x in events(output.getvalue()) if x["status"] == "STARTED"]
        self.assertEqual(
            started,
            ["pipeline", "bronze_collection", "silver_transformation", "silver_iceberg"],
        )
        self.assertTrue(spark.stopped)


if __name__ == "__main__":
    unittest.main()
