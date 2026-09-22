import io
import unittest
from unittest.mock import patch

from src.youtube_connectivity import fetch_seed_channels


class FakeResponse:
    def __init__(self, channel_id, title):
        self.body = (
            '{"items":[{"id":"%s","snippet":{"title":"%s"},'
            '"statistics":{"subscriberCount":"100","videoCount":"20"}}]}'
            % (channel_id, title)
        ).encode()

    def __enter__(self):
        return io.BytesIO(self.body)

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class YouTubeConnectivityTest(unittest.TestCase):
    @patch(
        "src.youtube_connectivity.urlopen",
        side_effect=[
            FakeResponse("channel-1", "RESCENE"),
            FakeResponse("channel-2", "WONI"),
        ],
    )
    def test_fetch_seed_channels_checks_both_handles(self, mocked_urlopen):
        result = fetch_seed_channels("test-key")

        self.assertEqual([channel["channel_id"] for channel in result], ["channel-1", "channel-2"])
        requested_urls = [call.args[0] for call in mocked_urlopen.call_args_list]
        self.assertIn("forHandle=%40RESCENE_official", requested_urls[0])
        self.assertIn(
            "forHandle=%40helloiamwoninicetomeetyou", requested_urls[1]
        )
        self.assertEqual(mocked_urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
