"""Fetch current YouTube video data for the RESCENE seed channels."""

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

if __package__:
    from .bronze_storage import BronzeStorage, BronzeStorageError
else:
    from bronze_storage import BronzeStorage, BronzeStorageError


API_BASE_URL = "https://www.googleapis.com/youtube/v3"
SEED_HANDLES = (
    "@RESCENE_official",
    "@helloiamwoninicetomeetyou",
)


class ConnectivityError(Exception):
    """Raised when the connectivity check cannot complete."""


class BronzeCapture:
    """Collect raw API responses for one logical run without persisting them."""

    def __init__(self, run_id: str | None = None, record_sink: Any = None) -> None:
        self.run_id = run_id or str(uuid4())
        self.records: list[dict[str, Any]] = []
        self.record_sink = record_sink

    def add(
        self,
        resource: str,
        request_context: dict[str, str | int],
        raw_payload: Any,
    ) -> None:
        safe_context = {
            name: deepcopy(value)
            for name, value in request_context.items()
            if name.lower() not in {"key", "api_key", "youtube_api_key"}
        }
        record = {
            "run_id": self.run_id,
            "source": "youtube",
            "resource": resource,
            "ingested_at": utc_now(),
            "request_context": safe_context,
            "raw_payload": deepcopy(raw_payload),
        }
        self.records.append(record)
        if self.record_sink is not None:
            self.record_sink(record)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def youtube_api_request(
    api_key: str,
    resource: str,
    params: dict[str, str | int],
    bronze: BronzeCapture | None = None,
) -> dict[str, Any]:
    query = urlencode({**params, "key": api_key})

    try:
        with urlopen(f"{API_BASE_URL}/{resource}?{query}", timeout=30) as response:
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

    if bronze is not None:
        bronze.add(resource, params, payload)
    if not isinstance(payload, dict):
        raise ConnectivityError(
            f"YouTube API returned an invalid {resource} response."
        )
    return payload


def required_text(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConnectivityError(f"Missing required {field} in {context}.")
    return value


def parse_count(value: Any, field: str, video_id: str, required: bool) -> int | None:
    if value is None and not required:
        return None
    try:
        count = int(value)
    except (TypeError, ValueError) as error:
        raise ConnectivityError(
            f"Invalid {field} for video {video_id}."
        ) from error
    if count < 0:
        raise ConnectivityError(f"Invalid {field} for video {video_id}.")
    return count


def parse_utc_timestamp(value: Any, field: str, context: str) -> str:
    text = required_text(value, field, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ConnectivityError(f"Invalid {field} in {context}.") from error
    if parsed.tzinfo is None:
        raise ConnectivityError(f"Invalid {field} in {context}: timezone is required.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_channel(
    api_key: str, handle: str, bronze: BronzeCapture | None = None
) -> dict[str, str]:
    payload = youtube_api_request(
        api_key,
        "channels",
        {
            "part": "snippet,statistics,contentDetails",
            "forHandle": handle,
        },
        bronze,
    )
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise ConnectivityError(f"YouTube API returned no channel for {handle}.")

    channel = items[0]
    if not isinstance(channel, dict):
        raise ConnectivityError(f"YouTube API returned an invalid channel for {handle}.")
    snippet = channel.get("snippet", {})
    statistics = channel.get("statistics", {})
    content_details = channel.get("contentDetails", {})
    uploads = content_details.get("relatedPlaylists", {}).get("uploads")
    subscriber_count = statistics.get("subscriberCount")
    if statistics.get("hiddenSubscriberCount"):
        subscriber_count = None

    return {
        "handle": handle,
        "channel_id": required_text(channel.get("id"), "channel ID", handle),
        "title": required_text(snippet.get("title"), "channel title", handle),
        "subscriber_count": subscriber_count or "unavailable",
        "video_count": statistics.get("videoCount", "unavailable"),
        "uploads_playlist_id": required_text(
            uploads, "uploads playlist ID", handle
        ),
    }


def fetch_seed_channels(
    api_key: str, bronze: BronzeCapture | None = None
) -> list[dict[str, str]]:
    return [fetch_channel(api_key, handle, bronze) for handle in SEED_HANDLES]


def discover_video_ids(
    api_key: str, playlist_id: str, bronze: BronzeCapture | None = None
) -> list[str]:
    video_ids: list[str] = []
    page_token: str | None = None
    seen_page_tokens: set[str] = set()

    while True:
        params: dict[str, str | int] = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        payload = youtube_api_request(api_key, "playlistItems", params, bronze)
        items = payload.get("items")
        if not isinstance(items, list):
            raise ConnectivityError(
                f"YouTube API returned invalid playlist items for {playlist_id}."
            )
        for item in items:
            if not isinstance(item, dict):
                raise ConnectivityError(
                    f"YouTube API returned an invalid playlist item for {playlist_id}."
                )
            video_ids.append(
                required_text(
                    item.get("contentDetails", {}).get("videoId"),
                    "video ID",
                    f"playlist {playlist_id}",
                )
            )

        next_page_token = payload.get("nextPageToken")
        if next_page_token is None:
            return video_ids
        page_token = required_text(
            next_page_token, "next page token", f"playlist {playlist_id}"
        )
        if page_token in seen_page_tokens:
            raise ConnectivityError(
                f"Repeated page token while reading playlist {playlist_id}."
            )
        seen_page_tokens.add(page_token)


def fetch_video_details(
    api_key: str,
    video_ids: list[str],
    observed_at: str,
    bronze: BronzeCapture | None = None,
) -> list[dict[str, Any]]:
    videos: list[dict[str, Any]] = []
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        payload = youtube_api_request(
            api_key,
            "videos",
            {"part": "snippet,statistics", "id": ",".join(batch)},
            bronze,
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise ConnectivityError("YouTube API returned invalid video items.")

        returned_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise ConnectivityError("YouTube API returned an invalid video item.")
            video_id = required_text(item.get("id"), "video ID", "video response")
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})
            if not isinstance(snippet, dict) or not isinstance(statistics, dict):
                raise ConnectivityError(f"Invalid fields for video {video_id}.")
            returned_ids.add(video_id)
            videos.append(
                {
                    "video_id": video_id,
                    "channel_id": required_text(
                        snippet.get("channelId"), "channel ID", f"video {video_id}"
                    ),
                    "title": required_text(
                        snippet.get("title"), "title", f"video {video_id}"
                    ),
                    "published_at": parse_utc_timestamp(
                        snippet.get("publishedAt"),
                        "published timestamp",
                        f"video {video_id}",
                    ),
                    "view_count": parse_count(
                        statistics.get("viewCount"), "view count", video_id, True
                    ),
                    "like_count": parse_count(
                        statistics.get("likeCount"), "like count", video_id, False
                    ),
                    "comment_count": parse_count(
                        statistics.get("commentCount"),
                        "comment count",
                        video_id,
                        False,
                    ),
                    "observed_at": observed_at,
                }
            )

        missing_ids = set(batch) - returned_ids
        if missing_ids:
            missing = ", ".join(sorted(missing_ids))
            raise ConnectivityError(f"YouTube API returned no data for videos: {missing}.")
    return videos


def collect_seed_videos(
    api_key: str, bronze: BronzeCapture | None = None
) -> list[dict[str, Any]]:
    observed_at = utc_now()
    videos: list[dict[str, Any]] = []
    for channel in fetch_seed_channels(api_key, bronze):
        video_ids = discover_video_ids(
            api_key, channel["uploads_playlist_id"], bronze
        )
        videos.extend(fetch_video_details(api_key, video_ids, observed_at, bronze))
    return videos


def main() -> int:
    try:
        api_key = get_api_key()
        storage = BronzeStorage.from_environment()
        storage.ensure_bucket()
        bronze = BronzeCapture(record_sink=storage.write_record)
        channels = fetch_seed_channels(api_key, bronze)
        observed_at = utc_now()
        videos_by_channel: list[tuple[dict[str, str], list[dict[str, Any]]]] = []
        for channel in channels:
            video_ids = discover_video_ids(
                api_key, channel["uploads_playlist_id"], bronze
            )
            videos_by_channel.append(
                (
                    channel,
                    fetch_video_details(api_key, video_ids, observed_at, bronze),
                )
            )
    except (ConnectivityError, BronzeStorageError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    for index, (channel, videos) in enumerate(videos_by_channel):
        if index:
            print()
        print(f"Handle: {channel['handle']}")
        print(f"Channel ID: {channel['channel_id']}")
        print(f"Channel title: {channel['title']}")
        print(f"Videos collected: {len(videos)}")
        if videos:
            sample = videos[0]
            print(f"Sample video ID: {sample['video_id']}")
    print(f"Observed at: {observed_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
