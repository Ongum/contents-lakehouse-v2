"""Fetch current YouTube video data for the RESCENE seed channels."""

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
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

    def __init__(
        self,
        run_id: str | None = None,
        observed_at: str | None = None,
        record_sink: Any = None,
        failure_sink: Any = None,
    ) -> None:
        self.run_id = run_id or str(uuid4())
        self.observed_at = observed_at or utc_now()
        self.records: list[dict[str, Any]] = []
        self.record_sink = record_sink
        self.failure_sink = failure_sink
        self.failures: list[dict[str, Any]] = []
        self.references: dict[str, str] = {}

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
            "observed_at": self.observed_at,
            "ingested_at": utc_now(),
            "request_context": safe_context,
            "raw_payload": deepcopy(raw_payload),
        }
        self.records.append(record)
        if self.record_sink is not None:
            reference = self.record_sink(record)
            self.references[self.request_key(resource, safe_context)] = reference

    @staticmethod
    def request_key(resource: str, context: dict[str, Any]) -> str:
        return json.dumps([resource, context], sort_keys=True)

    def fail(self, resource: str, context: dict[str, Any], error_type: str,
             message: str, *, item_index: int | None = None,
             video_id: str | None = None, cause: Exception | None = None) -> None:
        safe_context = {key: value for key, value in context.items()
                        if key in {'part', 'id', 'forHandle', 'playlistId', 'maxResults', 'pageToken'}}
        identity = [self.run_id, self.observed_at, resource, safe_context,
                    error_type, item_index, video_id]
        failure = {
            'failure_id': sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
            'run_id': self.run_id, 'source': 'youtube', 'resource': resource,
            'observed_at': self.observed_at, 'failed_at': utc_now(),
            'pipeline_stage': 'collection', 'request_context': safe_context,
            'source_reference': f'{API_BASE_URL}/{resource}',
            'payload_reference': self.references.get(self.request_key(resource, safe_context)),
            'item_index': item_index, 'video_id': video_id,
            'error_type': error_type, 'error_message': message,
            'cause_type': type(cause).__name__ if cause is not None else None,
            'http_status': cause.code if isinstance(cause, HTTPError) else None,
            'status': 'retryable' if error_type == 'request_failed' else 'unresolved',
            'retry_count': 0,
        }
        self.failures.append(failure)
        if self.failure_sink is not None:
            self.failure_sink(failure)

    def raise_for_failures(self) -> None:
        if self.failures:
            raise ConnectivityError(f'YouTube collection has {len(self.failures)} failure(s); '
                                    'successful payloads were retained. ' +
                                    '; '.join(row['error_message'] for row in self.failures))


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
    if bronze is not None:
        safe_context = {name: value for name, value in params.items()
                        if name.lower() not in {'key', 'api_key', 'youtube_api_key'}}
        bronze.references.pop(bronze.request_key(resource, safe_context), None)
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
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
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
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConnectivityError(f"Invalid {field} for video {video_id}.")
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
    try:
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except OverflowError as error:
        raise ConnectivityError(f"Invalid {field} in {context}.") from error


def optional_text(value: Any, field: str, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConnectivityError(f"Invalid {field} in {context}.")
    return value


def parse_caption(value: Any, video_id: str) -> bool | None:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise ConnectivityError(f"Invalid caption flag for video {video_id}.")


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
    owned_capture = bronze is None
    bronze = bronze or BronzeCapture()
    video_ids: list[str] = []
    page_token: str | None = None
    seen_page_tokens: set[str] = set()
    while True:
        params: dict[str, str | int] = {
            'part': 'contentDetails', 'playlistId': playlist_id, 'maxResults': 50,
        }
        if page_token:
            params['pageToken'] = page_token
        try:
            payload = youtube_api_request(api_key, 'playlistItems', params, bronze)
        except ConnectivityError as error:
            bronze.fail('playlistItems', params, 'request_failed', 'Uploads page request failed.',
                        cause=error.__cause__)
            break
        items = payload.get('items') if isinstance(payload, dict) else None
        if not isinstance(items, list):
            bronze.fail('playlistItems', params, 'invalid_response', 'Invalid uploads page items.')
            break
        for index, item in enumerate(items):
            try:
                video_ids.append(required_text(item.get('contentDetails', {}).get('videoId'),
                                               'video ID', 'uploads page'))
            except (ConnectivityError, AttributeError, TypeError):
                bronze.fail('playlistItems', params, 'invalid_playlist_item',
                            'Invalid uploads item.', item_index=index)
        next_token = payload.get('nextPageToken')
        if next_token is None:
            break
        if not isinstance(next_token, str) or not next_token or next_token in seen_page_tokens:
            bronze.fail('playlistItems', params, 'invalid_page_token', 'Invalid or repeated page token.')
            break
        seen_page_tokens.add(next_token)
        page_token = next_token
    if owned_capture:
        bronze.raise_for_failures()
    return list(dict.fromkeys(video_ids))


def _parse_video(item: Any, observed_at: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ConnectivityError("YouTube API returned an invalid video item.")
    video_id = required_text(item.get("id"), "video ID", "video response")
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    content_details = item.get("contentDetails", {})
    if (
        not isinstance(snippet, dict)
        or not isinstance(statistics, dict)
        or not isinstance(content_details, dict)
    ):
        raise ConnectivityError(f"Invalid fields for video {video_id}.")
    tags = snippet.get("tags")
    if tags is not None and (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
    ):
        raise ConnectivityError(f"Invalid tags for video {video_id}.")
    return {
        "video_id": video_id,
        "channel_id": required_text(
            snippet.get("channelId"), "channel ID", f"video {video_id}"
        ),
        "title": required_text(
            snippet.get("title"), "title", f"video {video_id}"
        ),
        "description": optional_text(
            snippet.get("description"),
            "description",
            f"video {video_id}",
        ),
        "channel_title": optional_text(
            snippet.get("channelTitle"),
            "channel title",
            f"video {video_id}",
        ),
        "tags": tags,
        "category_id": optional_text(
            snippet.get("categoryId"),
            "category ID",
            f"video {video_id}",
        ),
        "duration": optional_text(
            content_details.get("duration"),
            "duration",
            f"video {video_id}",
        ),
        "caption": parse_caption(
            content_details.get("caption"), video_id
        ),
        "definition": optional_text(
            content_details.get("definition"),
            "definition",
            f"video {video_id}",
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


def fetch_video_details(
    api_key: str,
    video_ids: list[str],
    observed_at: str,
    bronze: BronzeCapture | None = None,
) -> list[dict[str, Any]]:
    owned_capture = bronze is None
    bronze = bronze or BronzeCapture(observed_at=observed_at)
    videos: list[dict[str, Any]] = []
    video_ids = list(dict.fromkeys(video_ids))
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        params = {'part': 'snippet,statistics,contentDetails', 'id': ','.join(batch)}
        try:
            payload = youtube_api_request(api_key, 'videos', params, bronze)
        except ConnectivityError as error:
            bronze.fail('videos', params, 'request_failed', 'Video batch request failed.',
                        cause=error.__cause__)
            continue
        items = payload.get('items') if isinstance(payload, dict) else None
        if not isinstance(items, list):
            bronze.fail('videos', params, 'invalid_response', 'Video response items must be an array.')
            continue
        returned_ids: set[str] = set()
        for index, item in enumerate(items):
            video_id = item.get('id') if isinstance(item, dict) else None
            if isinstance(video_id, str) and video_id in batch:
                if video_id in returned_ids:
                    bronze.fail('videos', params, 'duplicate_video', 'Duplicate video item.',
                                item_index=index, video_id=video_id)
                    continue
                returned_ids.add(video_id)
            try:
                if not isinstance(video_id, str) or video_id not in batch:
                    raise ConnectivityError('Video item has no requested ID.')
                videos.append(_parse_video(item, observed_at))
            except (ConnectivityError, AttributeError, TypeError, ValueError):
                bronze.fail('videos', params, 'invalid_video', 'Video item failed validation.',
                            item_index=index, video_id=video_id if isinstance(video_id, str) else None)
        for video_id in sorted(set(batch) - returned_ids):
            bronze.fail('videos', params, 'unavailable_video',
                        f'YouTube returned no data for video {video_id}.', video_id=video_id)
    if owned_capture:
        bronze.raise_for_failures()
    return videos



def collect_seed_videos(
    api_key: str, bronze: BronzeCapture | None = None
) -> list[dict[str, Any]]:
    owned_capture = bronze is None
    bronze = bronze or BronzeCapture()
    videos: list[dict[str, Any]] = []
    for handle in SEED_HANDLES:
        try:
            channel = fetch_channel(api_key, handle, bronze)
        except (ConnectivityError, AttributeError, TypeError, ValueError) as error:
            bronze.fail('channels', {'part': 'snippet,statistics,contentDetails', 'forHandle': handle},
                        'request_failed', 'Channel request or validation failed.',
                        cause=error.__cause__ or error)
            continue
        video_ids = discover_video_ids(api_key, channel['uploads_playlist_id'], bronze)
        videos.extend(fetch_video_details(api_key, video_ids, bronze.observed_at, bronze))
    if owned_capture:
        bronze.raise_for_failures()
    return videos


def main() -> int:
    try:
        api_key = get_api_key()
        storage = BronzeStorage.from_environment()
        storage.ensure_bucket()
        bronze = BronzeCapture(record_sink=storage.write_record, failure_sink=storage.write_failure)
        videos = collect_seed_videos(api_key, bronze)
        bronze.raise_for_failures()
    except (ConnectivityError, BronzeStorageError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f'Videos collected: {len(videos)}')
    print(f'Observed at: {bronze.observed_at}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
