"""Transform persisted YouTube Bronze envelopes into in-memory Silver records."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SilverResult:
    youtube_channels: list[dict[str, Any]] = field(default_factory=list)
    youtube_videos: list[dict[str, Any]] = field(default_factory=list)
    video_metrics_snapshots: list[dict[str, Any]] = field(default_factory=list)
    lineage: list[dict[str, Any]] = field(default_factory=list)
    invalid_records: list[dict[str, Any]] = field(default_factory=list)


class RecordValidationError(ValueError):
    """Raised for one invalid Bronze item that can be isolated."""


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RecordValidationError(f"Missing required {field_name}.")
    return value


def _utc_timestamp(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise RecordValidationError(f"Invalid {field_name}.") from error
    if parsed.tzinfo is None:
        raise RecordValidationError(f"Invalid {field_name}: timezone is required.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _count(value: Any, field_name: str, required: bool) -> int | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RecordValidationError(f"Invalid {field_name}.")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise RecordValidationError(f"Invalid {field_name}.") from error
    if result < 0:
        raise RecordValidationError(f"Invalid {field_name}.")
    return result


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecordValidationError(f"Invalid {field_name}.")
    return value


def _optional_tags(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
        raise RecordValidationError("Invalid tags.")
    return value


def _optional_caption(value: Any) -> bool | None:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if isinstance(value, bool):
        return value
    raise RecordValidationError("Invalid caption flag.")


def _invalid(
    source_reference: str,
    run_id: str | None,
    resource: str | None,
    message: str,
    item_index: int | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "pipeline_stage": "bronze_to_silver",
        "source_reference": source_reference,
        "resource": resource,
        "item_index": item_index,
        "error_type": "record_validation_error",
        "error_message": message,
    }


def _lineage(
    record_type: str,
    record_key: tuple[Any, ...],
    run_id: str,
    source_reference: str,
) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "record_key": record_key,
        "run_id": run_id,
        "source_reference": source_reference,
    }


def _upsert(
    records: dict[tuple[Any, ...], tuple[str, dict[str, Any]]],
    key: tuple[Any, ...],
    ingested_at: str,
    record: dict[str, Any],
) -> None:
    current = records.get(key)
    if current is None or ingested_at >= current[0]:
        records[key] = (ingested_at, record)


def _upsert_lineage(
    lineage: dict[tuple[str, tuple[Any, ...]], tuple[str, dict[str, Any]]],
    record_type: str,
    record_key: tuple[Any, ...],
    ingested_at: str,
    run_id: str,
    source_reference: str,
) -> None:
    key = (record_type, record_key)
    current = lineage.get(key)
    if current is None or ingested_at >= current[0]:
        lineage[key] = (
            ingested_at,
            _lineage(record_type, record_key, run_id, source_reference),
        )


def transform_bronze_objects(
    bronze_objects: list[tuple[str, dict[str, Any]]],
    channel_mapping: dict[str, dict[str, Any]],
) -> SilverResult:
    result = SilverResult()
    prepared: list[
        tuple[str, dict[str, Any], str, str, str, str, dict[str, Any]]
    ] = []
    run_observation_times: dict[str, set[str]] = {}

    for source_reference, envelope in bronze_objects:
        try:
            if not isinstance(envelope, dict):
                raise RecordValidationError("Bronze envelope must be an object.")
            run_id = _required_text(envelope.get("run_id"), "run_id")
            source = _required_text(envelope.get("source"), "source")
            if source != "youtube":
                raise RecordValidationError("Unsupported Bronze source.")
            resource = _required_text(envelope.get("resource"), "resource")
            observed_at = _utc_timestamp(
                envelope.get("observed_at"), "observed_at"
            )
            ingested_at = _utc_timestamp(envelope.get("ingested_at"), "ingested_at")
            request_context = envelope.get("request_context")
            raw_payload = envelope.get("raw_payload")
            if not isinstance(request_context, dict):
                raise RecordValidationError("request_context must be an object.")
            if not isinstance(raw_payload, dict):
                raise RecordValidationError("raw_payload must be an object.")
            prepared.append(
                (
                    source_reference,
                    envelope,
                    run_id,
                    resource,
                    observed_at,
                    ingested_at,
                    request_context,
                )
            )
            run_observation_times.setdefault(run_id, set()).add(observed_at)
        except RecordValidationError as error:
            result.invalid_records.append(
                _invalid(
                    source_reference,
                    envelope.get("run_id") if isinstance(envelope, dict) else None,
                    envelope.get("resource") if isinstance(envelope, dict) else None,
                    str(error),
                )
            )

    channels: dict[tuple[Any, ...], tuple[str, dict[str, Any]]] = {}
    videos: dict[tuple[Any, ...], tuple[str, dict[str, Any]]] = {}
    snapshots: dict[tuple[Any, ...], tuple[str, dict[str, Any]]] = {}
    selected_lineage: dict[
        tuple[str, tuple[Any, ...]], tuple[str, dict[str, Any]]
    ] = {}

    inconsistent_runs = {
        run_id
        for run_id, observed_values in run_observation_times.items()
        if len(observed_values) != 1
    }

    for (
        source_reference,
        envelope,
        run_id,
        resource,
        observed_at,
        ingested_at,
        request_context,
    ) in prepared:
        if run_id in inconsistent_runs:
            result.invalid_records.append(
                _invalid(
                    source_reference,
                    run_id,
                    resource,
                    "Run contains inconsistent observed_at values.",
                )
            )
            continue
        raw_payload = envelope["raw_payload"]
        items = raw_payload.get("items")
        if not isinstance(items, list):
            result.invalid_records.append(
                _invalid(
                    source_reference,
                    run_id,
                    resource,
                    "raw_payload.items must be an array.",
                )
            )
            continue

        if resource not in {"channels", "playlistItems", "videos"}:
            result.invalid_records.append(
                _invalid(
                    source_reference,
                    run_id,
                    resource,
                    "Unsupported YouTube resource.",
                )
            )
            continue

        for item_index, item in enumerate(items):
            try:
                if not isinstance(item, dict):
                    raise RecordValidationError("API item must be an object.")

                if resource == "playlistItems":
                    _required_text(
                        item.get("contentDetails", {}).get("videoId"), "video_id"
                    )
                    continue

                if resource == "channels":
                    handle = _required_text(
                        request_context.get("forHandle"), "request handle"
                    )
                    mapping = channel_mapping.get(handle)
                    if mapping is None:
                        raise RecordValidationError(
                            f"No channel mapping configured for {handle}."
                        )
                    channel_id = _required_text(item.get("id"), "channel_id")
                    snippet = item.get("snippet")
                    if not isinstance(snippet, dict):
                        raise RecordValidationError("Missing channel snippet.")
                    is_official = mapping.get("is_official")
                    if not isinstance(is_official, bool):
                        raise RecordValidationError(
                            "Channel is_official mapping must be boolean."
                        )
                    channel = {
                        "channel_id": channel_id,
                        "artist_id": _required_text(
                            mapping.get("artist_id"), "artist_id"
                        ),
                        "channel_title": _required_text(
                            snippet.get("title"), "channel_title"
                        ),
                        "is_official": is_official,
                        "source_updated_at": None,
                    }
                    key = (channel_id,)
                    _upsert(channels, key, ingested_at, channel)
                    _upsert_lineage(
                        selected_lineage,
                        "youtube_channel",
                        key,
                        ingested_at,
                        run_id,
                        source_reference,
                    )
                    continue

                video_id = _required_text(item.get("id"), "video_id")
                snippet = item.get("snippet")
                statistics = item.get("statistics")
                content_details = item.get("contentDetails", {})
                if not isinstance(snippet, dict):
                    raise RecordValidationError("Missing video snippet.")
                if not isinstance(statistics, dict):
                    raise RecordValidationError("Missing video statistics.")
                if not isinstance(content_details, dict):
                    raise RecordValidationError("Invalid video contentDetails.")
                video = {
                    "video_id": video_id,
                    "channel_id": _required_text(
                        snippet.get("channelId"), "channel_id"
                    ),
                    "title": _required_text(snippet.get("title"), "title"),
                    "description": _optional_text(
                        snippet.get("description"), "description"
                    ),
                    "channel_title": _optional_text(
                        snippet.get("channelTitle"), "channel_title"
                    ),
                    "tags": _optional_tags(snippet.get("tags")),
                    "category_id": _optional_text(
                        snippet.get("categoryId"), "category_id"
                    ),
                    "duration": _optional_text(
                        content_details.get("duration"), "duration"
                    ),
                    "caption": _optional_caption(content_details.get("caption")),
                    "definition": _optional_text(
                        content_details.get("definition"), "definition"
                    ),
                    "published_at": _utc_timestamp(
                        snippet.get("publishedAt"), "published_at"
                    ),
                    "source_updated_at": None,
                }
                snapshot = {
                    "video_id": video_id,
                    "observed_at": observed_at,
                    "view_count": _count(
                        statistics.get("viewCount"), "view_count", True
                    ),
                    "like_count": _count(
                        statistics.get("likeCount"), "like_count", False
                    ),
                    "comment_count": _count(
                        statistics.get("commentCount"), "comment_count", False
                    ),
                }
                video_key = (video_id,)
                snapshot_key = (video_id, observed_at)
                _upsert(videos, video_key, ingested_at, video)
                _upsert(snapshots, snapshot_key, ingested_at, snapshot)
                _upsert_lineage(
                    selected_lineage,
                    "youtube_video",
                    video_key,
                    ingested_at,
                    run_id,
                    source_reference,
                )
                _upsert_lineage(
                    selected_lineage,
                    "video_metrics_snapshot",
                    snapshot_key,
                    ingested_at,
                    run_id,
                    source_reference,
                )
            except (RecordValidationError, AttributeError) as error:
                result.invalid_records.append(
                    _invalid(
                        source_reference,
                        run_id,
                        resource,
                        str(error),
                        item_index,
                    )
                )

    result.youtube_channels = [value[1] for _, value in sorted(channels.items())]
    result.youtube_videos = [value[1] for _, value in sorted(videos.items())]
    result.video_metrics_snapshots = [
        value[1] for _, value in sorted(snapshots.items())
    ]
    result.lineage = [value[1] for _, value in sorted(selected_lineage.items())]
    return result


def transform_from_minio(
    storage: Any, channel_mapping: dict[str, dict[str, Any]]
) -> SilverResult:
    """Read persisted Bronze objects and transform them without API access."""
    return transform_bronze_objects(storage.list_records(), channel_mapping)
