"""Verify Bronze-to-Silver reconstruction against isolated MinIO objects."""

from pathlib import Path
from uuid import uuid4

if __package__:
    from .bronze_storage import BronzeStorage, BronzeStorageError
    from .mvp_config import RESCENE_CHANNELS
    from .silver_transform import transform_bronze_objects
    from .youtube_connectivity import load_local_env
else:
    from bronze_storage import BronzeStorage, BronzeStorageError
    from mvp_config import RESCENE_CHANNELS
    from silver_transform import transform_bronze_objects
    from youtube_connectivity import load_local_env


def main() -> int:
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    storage = BronzeStorage.from_environment()
    storage.ensure_bucket()
    run_id = f"silver-verification-{uuid4()}"
    observed_at = "2026-09-22T00:00:00Z"
    ingested_at = "2026-09-22T00:00:00Z"
    records = [
        {
            "run_id": run_id,
            "source": "youtube",
            "resource": "channels",
            "observed_at": observed_at,
            "ingested_at": ingested_at,
            "request_context": {
                "part": "snippet,statistics,contentDetails",
                "forHandle": "@RESCENE_official",
            },
            "raw_payload": {
                "items": [
                    {"id": "verification-channel", "snippet": {"title": "RESCENE"}}
                ]
            },
        },
        {
            "run_id": run_id,
            "source": "youtube",
            "resource": "videos",
            "observed_at": observed_at,
            "ingested_at": "2026-09-22T00:01:00Z",
            "request_context": {"part": "snippet,statistics", "id": "verification-video"},
            "raw_payload": {
                "items": [
                    {
                        "id": "verification-video",
                        "snippet": {
                            "channelId": "verification-channel",
                            "title": "Verification Video",
                            "publishedAt": "2026-09-21T12:00:00Z",
                        },
                        "statistics": {"viewCount": "10"},
                    }
                ]
            },
        },
    ]
    object_names: list[str] = []

    try:
        object_names = [storage.write_record(record) for record in records]
        persisted = [
            item
            for item in storage.list_records()
            if item[1].get("run_id") == run_id
        ]
        result = transform_bronze_objects(persisted, RESCENE_CHANNELS)
        if (
            len(result.youtube_channels) != 1
            or len(result.youtube_videos) != 1
            or len(result.video_metrics_snapshots) != 1
            or result.video_metrics_snapshots[0]["observed_at"] != observed_at
            or result.invalid_records
        ):
            raise BronzeStorageError("Bronze-to-Silver verification failed.")
        print(
            "MinIO Bronze-to-Silver verification succeeded: "
            "1 channel, 1 video, 1 metrics snapshot"
        )
    finally:
        for object_name in object_names:
            storage.client.remove_object(storage.bucket, object_name)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BronzeStorageError as error:
        raise SystemExit(f"Error: {error}") from error
