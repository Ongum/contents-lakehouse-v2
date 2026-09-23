import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import run_advertising_collection
import run_mediawiki_collection
import run_youtube_collection
from advertising_collection import CollectionStatus


class CollectionEntrypointTest(unittest.TestCase):
    def test_youtube_runs_collection_only(self) -> None:
        storage = Mock()

        def collect(_key, capture):
            capture.records.extend([{}, {}])
            return [{"video_id": "one"}]

        with patch.object(
            run_youtube_collection, "bronze_storage_from_environment", return_value=storage
        ), patch.object(run_youtube_collection, "get_api_key", return_value="secret"), patch.object(
            run_youtube_collection, "collect_seed_videos", side_effect=collect
        ):
            self.assertEqual(run_youtube_collection.main(), 0)
        storage.ensure_bucket.assert_called_once_with()

    def test_mediawiki_runs_collection_only(self) -> None:
        storage = Mock()
        result = ("bronze/mediawiki/object.json", False, {"revision_id": 123})
        with patch.object(
            run_mediawiki_collection, "bronze_storage_from_environment", return_value=storage
        ), patch.object(
            run_mediawiki_collection, "ingest_latest_revision", return_value=result
        ):
            self.assertEqual(run_mediawiki_collection.main(), 0)
        storage.ensure_bucket.assert_called_once_with()

    def test_advertising_propagates_collection_failure(self) -> None:
        storage = Mock()
        result = SimpleNamespace(
            status=CollectionStatus.RETRYABLE_FAILURE,
            error_message="unavailable",
            object_key=None,
        )
        with patch.object(
            run_advertising_collection,
            "bronze_storage_from_environment",
            return_value=storage,
        ), patch.object(run_advertising_collection, "collect_source", return_value=result):
            self.assertEqual(run_advertising_collection.main(), 1)


if __name__ == "__main__":
    unittest.main()
