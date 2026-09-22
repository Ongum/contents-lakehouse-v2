import io
import json
import unittest
from unittest.mock import patch

from src.youtube_connectivity import BronzeCapture, youtube_api_request


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return io.BytesIO(self.body)

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class BronzeCaptureTest(unittest.TestCase):
    @patch(
        "src.youtube_connectivity.urlopen",
        side_effect=[
            FakeResponse({"items": [{"id": "channel-1"}]}),
            FakeResponse({"items": [{"id": "playlist-item-1"}]}),
            FakeResponse({"items": [{"id": "video-1"}]}),
        ],
    )
    def test_preserves_raw_responses_with_one_run_id_and_no_api_key(self, _urlopen):
        bronze = BronzeCapture(run_id="run-123")
        resources = ("channels", "playlistItems", "videos")

        responses = [
            youtube_api_request(
                "secret-api-key",
                resource,
                {"part": "snippet", "key": "must-not-be-stored"},
                bronze,
            )
            for resource in resources
        ]
        responses[0]["items"][0]["id"] = "changed-after-capture"

        self.assertEqual(len(bronze.records), 3)
        self.assertEqual(
            {record["run_id"] for record in bronze.records}, {"run-123"}
        )
        self.assertEqual(
            [record["resource"] for record in bronze.records], list(resources)
        )
        self.assertEqual(
            bronze.records[0]["raw_payload"],
            {"items": [{"id": "channel-1"}]},
        )
        self.assertTrue(
            all(record["ingested_at"].endswith("Z") for record in bronze.records)
        )
        serialized = json.dumps(bronze.records)
        self.assertNotIn("secret-api-key", serialized)
        self.assertNotIn("must-not-be-stored", serialized)
        self.assertTrue(
            all(record["source"] == "youtube" for record in bronze.records)
        )


if __name__ == "__main__":
    unittest.main()
