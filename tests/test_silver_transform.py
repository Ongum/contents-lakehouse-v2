import unittest

from src.mvp_config import RESCENE_ARTIST_ID, RESCENE_CHANNELS
from src.silver_transform import transform_bronze_objects


def envelope(
    resource,
    payload,
    reference,
    ingested_at="2026-09-22T01:00:00Z",
    observed_at="2026-09-22T00:30:00Z",
):
    request_context = {"part": "snippet,statistics"}
    if resource == "channels":
        request_context["forHandle"] = "@RESCENE_official"
    return (
        reference,
        {
            "run_id": "run-1",
            "source": "youtube",
            "resource": resource,
            "observed_at": observed_at,
            "ingested_at": ingested_at,
            "request_context": request_context,
            "raw_payload": payload,
        },
    )


class SilverTransformTest(unittest.TestCase):
    def test_transforms_channel_video_metrics_and_lineage_without_api(self):
        bronze_objects = [
            envelope(
                "channels",
                {"items": [{"id": "channel-1", "snippet": {"title": "RESCENE"}}]},
                "bronze/channels.json",
            ),
            envelope(
                "videos",
                {
                    "items": [
                        {
                            "id": "video-1",
                            "snippet": {
                                "channelId": "channel-1",
                                "title": "Video One",
                                "publishedAt": "2026-09-20T02:00:00Z",
                            },
                            "statistics": {"viewCount": "100"},
                        }
                    ]
                },
                "bronze/videos.json",
                "2026-09-22T01:05:00Z",
            ),
        ]

        result = transform_bronze_objects(bronze_objects, RESCENE_CHANNELS)

        self.assertEqual(
            result.youtube_channels,
            [
                {
                    "channel_id": "channel-1",
                    "artist_id": RESCENE_ARTIST_ID,
                    "channel_title": "RESCENE",
                    "is_official": True,
                    "source_updated_at": None,
                }
            ],
        )
        self.assertEqual(result.youtube_videos[0]["video_id"], "video-1")
        self.assertEqual(result.youtube_videos[0]["published_at"], "2026-09-20T02:00:00Z")
        self.assertEqual(
            result.video_metrics_snapshots,
            [
                {
                    "video_id": "video-1",
                    "observed_at": "2026-09-22T00:30:00Z",
                    "view_count": 100,
                    "like_count": None,
                    "comment_count": None,
                }
            ],
        )
        self.assertFalse(result.invalid_records)
        self.assertIn(
            "bronze/videos.json",
            {entry["source_reference"] for entry in result.lineage},
        )

    def test_marks_only_configured_official_channel_as_official(self):
        related = envelope(
            "channels",
            {"items": [{"id": "channel-2", "snippet": {"title": "WONI"}}]},
            "bronze/related-channel.json",
        )
        related[1]["request_context"]["forHandle"] = (
            "@helloiamwoninicetomeetyou"
        )

        result = transform_bronze_objects([related], RESCENE_CHANNELS)

        self.assertFalse(result.youtube_channels[0]["is_official"])

    def test_deduplicates_by_canonical_keys_and_uses_one_run_timestamp(self):
        payload = {
            "items": [
                {
                    "id": "video-1",
                    "snippet": {
                        "channelId": "channel-1",
                        "title": "Original",
                        "publishedAt": "2026-09-20T02:00:00Z",
                    },
                    "statistics": {
                        "viewCount": "10",
                        "likeCount": "2",
                        "commentCount": "1",
                    },
                }
            ]
        }
        newer_payload = {"items": [{**payload["items"][0]}]}
        newer_payload["items"][0]["snippet"] = {
            **payload["items"][0]["snippet"],
            "title": "Updated",
        }
        objects = [
            envelope("videos", payload, "bronze/first.json", "2026-09-22T01:05:00Z"),
            envelope(
                "videos",
                newer_payload,
                "bronze/second.json",
                "2026-09-22T01:10:00Z",
            ),
        ]

        result = transform_bronze_objects(objects, RESCENE_CHANNELS)

        self.assertEqual(len(result.youtube_videos), 1)
        self.assertEqual(result.youtube_videos[0]["title"], "Updated")
        self.assertEqual(len(result.video_metrics_snapshots), 1)
        self.assertEqual(
            result.video_metrics_snapshots[0]["observed_at"],
            "2026-09-22T00:30:00Z",
        )
        self.assertEqual(
            {
                entry["source_reference"]
                for entry in result.lineage
                if entry["record_type"] == "youtube_video"
            },
            {"bronze/second.json"},
        )

    def test_surfaces_malformed_item_without_dropping_valid_item(self):
        payload = {
            "items": [
                {
                    "id": "video-valid",
                    "snippet": {
                        "channelId": "channel-1",
                        "title": "Valid",
                        "publishedAt": "2026-09-20T02:00:00Z",
                    },
                    "statistics": {"viewCount": "5"},
                },
                {
                    "id": "video-invalid",
                    "snippet": {
                        "channelId": "channel-1",
                        "title": "Invalid",
                        "publishedAt": "not-a-timestamp",
                    },
                    "statistics": {"viewCount": "-1"},
                },
            ]
        }

        result = transform_bronze_objects(
            [envelope("videos", payload, "bronze/mixed.json")],
            RESCENE_CHANNELS,
        )

        self.assertEqual([item["video_id"] for item in result.youtube_videos], ["video-valid"])
        self.assertEqual(len(result.invalid_records), 1)
        self.assertEqual(result.invalid_records[0]["source_reference"], "bronze/mixed.json")
        self.assertEqual(result.invalid_records[0]["item_index"], 1)

    def test_rejects_inconsistent_observed_at_within_one_run(self):
        payload = {
            "items": [
                {
                    "id": "video-1",
                    "snippet": {
                        "channelId": "channel-1",
                        "title": "Video",
                        "publishedAt": "2026-09-20T02:00:00Z",
                    },
                    "statistics": {"viewCount": "5"},
                }
            ]
        }
        objects = [
            envelope(
                "videos",
                payload,
                "bronze/first.json",
                observed_at="2026-09-22T00:30:00Z",
            ),
            envelope(
                "videos",
                payload,
                "bronze/second.json",
                observed_at="2026-09-22T00:31:00Z",
            ),
        ]

        result = transform_bronze_objects(objects, RESCENE_CHANNELS)

        self.assertFalse(result.youtube_videos)
        self.assertFalse(result.video_metrics_snapshots)
        self.assertEqual(len(result.invalid_records), 2)
        self.assertTrue(
            all(
                "inconsistent observed_at" in failure["error_message"]
                for failure in result.invalid_records
            )
        )


if __name__ == "__main__":
    unittest.main()
