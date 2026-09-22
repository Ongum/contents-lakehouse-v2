"""Minimal YouTube Data API connectivity check for RESCENE seed channels."""

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


API_URL = "https://www.googleapis.com/youtube/v3/channels"
SEED_HANDLES = (
    "@RESCENE_official",
    "@helloiamwoninicetomeetyou",
)


class ConnectivityError(Exception):
    """Raised when the connectivity check cannot complete."""


def load_local_env(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding the environment."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name.strip(), value)


def get_api_key() -> str:
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise ConnectivityError(
            "YOUTUBE_API_KEY is missing. Set it in the environment or local .env file."
        )
    return api_key


def fetch_channel(api_key: str, handle: str) -> dict[str, str]:
    query = urlencode(
        {
            "part": "snippet,statistics",
            "forHandle": handle,
            "key": api_key,
        }
    )

    try:
        with urlopen(f"{API_URL}?{query}", timeout=10) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise ConnectivityError(
            f"YouTube API request failed with HTTP {error.code}. "
            "Check the API key, API enablement, and quota."
        ) from error
    except URLError as error:
        raise ConnectivityError(
            f"YouTube API request failed due to a network error: {error.reason}"
        ) from error
    except (json.JSONDecodeError, OSError) as error:
        raise ConnectivityError("YouTube API returned an unreadable response.") from error

    items = payload.get("items", [])
    if not items:
        raise ConnectivityError(f"YouTube API returned no channel for {handle}.")

    channel = items[0]
    snippet = channel.get("snippet", {})
    statistics = channel.get("statistics", {})
    subscriber_count = statistics.get("subscriberCount")
    if statistics.get("hiddenSubscriberCount"):
        subscriber_count = None

    return {
        "handle": handle,
        "channel_id": channel.get("id", "unavailable"),
        "title": snippet.get("title", "unavailable"),
        "subscriber_count": subscriber_count or "unavailable",
        "video_count": statistics.get("videoCount", "unavailable"),
    }


def fetch_seed_channels(api_key: str) -> list[dict[str, str]]:
    return [fetch_channel(api_key, handle) for handle in SEED_HANDLES]


def main() -> int:
    try:
        channels = fetch_seed_channels(get_api_key())
    except ConnectivityError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    for index, channel in enumerate(channels):
        if index:
            print()
        print(f"Handle: {channel['handle']}")
        print(f"Channel ID: {channel['channel_id']}")
        print(f"Channel title: {channel['title']}")
        print(f"Subscribers: {channel['subscriber_count']}")
        print(f"Videos: {channel['video_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
