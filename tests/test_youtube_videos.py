import unittest
from unittest.mock import patch

from src.youtube_connectivity import (
    ConnectivityError,
    discover_video_ids,
    fetch_video_details,
)


class YouTubeVideosTest(unittest.TestCase):
    @patch("src.youtube_connectivity.youtube_api_request")
    def test_discover_video_ids_follows_pagination(self, request):
        request.side_effect = [
            {
                "items": [{"contentDetails": {"videoId": "video-1"}}],
                "nextPageToken": "next-page",
            },
            {"items": [{"contentDetails": {"videoId": "video-2"}}]},
        ]

        self.assertEqual(
            discover_video_ids("test-key", "uploads-1"),
            ["video-1", "video-2"],
        )
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("pageToken", request.call_args_list[0].args[2])
        self.assertEqual(
            request.call_args_list[1].args[2]["pageToken"], "next-page"
        )

    @patch("src.youtube_connectivity.youtube_api_request")
    def test_fetch_video_details_batches_and_preserves_null_metrics(self, request):
        video_ids = [f"video-{index}" for index in range(51)]

        def response(_api_key, resource, params, _bronze=None):
            self.assertEqual(resource, "videos")
            return {
                "items": [
                    {
                        "id": video_id,
                        "snippet": {
                            "channelId": "channel-1",
                            "title": f"Title {video_id}",
                            "publishedAt": "2026-01-02T03:04:05Z",
                        },
                        "statistics": {
                            "viewCount": "10",
                            **(
                                {}
                                if video_id == "video-0"
                                else {"likeCount": "7", "commentCount": "3"}
                            ),
                        },
                    }
                    for video_id in params["id"].split(",")
                ]
            }

        request.side_effect = response
        result = fetch_video_details(
            "test-key", video_ids, "2026-09-22T01:00:00Z"
        )

        self.assertEqual(len(result), 51)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result[0]["view_count"], 10)
        self.assertIsNone(result[0]["like_count"])
        self.assertIsNone(result[0]["comment_count"])
        self.assertEqual(result[1]["like_count"], 7)
        self.assertEqual(result[1]["comment_count"], 3)
        self.assertEqual(result[0]["observed_at"], "2026-09-22T01:00:00Z")

    @patch("src.youtube_connectivity.youtube_api_request")
    def test_missing_video_response_fails_instead_of_dropping_record(self, request):
        request.return_value = {"items": []}

        with self.assertRaisesRegex(ConnectivityError, "video-missing"):
            fetch_video_details(
                "test-key", ["video-missing"], "2026-09-22T01:00:00Z"
            )


if __name__ == "__main__":
    unittest.main()
