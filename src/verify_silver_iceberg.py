"""Verify isolated Bronze-to-Silver Iceberg persistence and idempotency."""

import os
from uuid import uuid4

from bronze_storage import BronzeStorage, BronzeStorageError
from mvp_config import RESCENE_CHANNELS
from silver_iceberg import (
    SilverPersistenceError,
    build_spark_session,
    persist_silver_result,
)
from silver_transform import transform_bronze_objects


def main() -> int:
    storage = BronzeStorage.from_environment()
    storage.ensure_bucket()
    run_id = f"iceberg-verification-{uuid4()}"
    observed_at = "2026-09-22T01:23:45Z"
    records = [
        {
            "run_id": run_id,
            "source": "youtube",
            "resource": "channels",
            "observed_at": observed_at,
            "ingested_at": "2026-09-22T01:23:46Z",
            "request_context": {"forHandle": "@RESCENE_official"},
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
            "ingested_at": "2026-09-22T01:23:47Z",
            "request_context": {"id": "verification-video"},
            "raw_payload": {
                "items": [
                    {
                        "id": "verification-video",
                        "snippet": {
                            "channelId": "verification-channel",
                            "title": "Verification Video",
                            "publishedAt": "2026-09-21T12:00:00Z",
                            "description": "Verification description",
                            "channelTitle": "RESCENE",
                            "tags": ["verification", "music"],
                            "categoryId": "10",
                        },
                        "contentDetails": {
                            "duration": "PT2M30S",
                            "caption": "true",
                            "definition": "hd",
                        },
                        "statistics": {"viewCount": "10"},
                    }
                ]
            },
        },
    ]
    object_names = [storage.write_record(record) for record in records]
    persisted = [(name, storage.read_record(name)) for name in object_names]
    result = transform_bronze_objects(persisted, RESCENE_CHANNELS)
    if result.invalid_records:
        raise SilverPersistenceError("Synthetic Bronze transformation failed.")

    spark = build_spark_session()
    try:
        catalog = os.environ.get("ICEBERG_CATALOG", "lakehouse")
        namespace = os.environ.get("SILVER_NAMESPACE", "silver")
        spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.youtube_video ("
            "video_id STRING NOT NULL, channel_id STRING NOT NULL, "
            "title STRING NOT NULL, published_at TIMESTAMP NOT NULL, "
            "source_updated_at TIMESTAMP) USING iceberg "
            "TBLPROPERTIES ('format-version' = '2')"
        )
        persist_silver_result(spark, result)
        persist_silver_result(spark, result)
        expected = {
            "youtube_channel": 1,
            "youtube_video": 1,
            "video_metrics_snapshot": 1,
        }
        for table, count in expected.items():
            actual = spark.table(f"{catalog}.{namespace}.{table}").count()
            if actual != count:
                raise SilverPersistenceError(
                    f"Expected {count} {table} row(s), found {actual}."
                )
        channel = spark.table(f"{catalog}.{namespace}.youtube_channel").first()
        video = spark.table(f"{catalog}.{namespace}.youtube_video").first()
        metrics = spark.table(
            f"{catalog}.{namespace}.video_metrics_snapshot"
        ).first()
        if (
            channel.channel_id != "verification-channel"
            or channel.artist_id != "artist_rescene"
            or channel.channel_title != "RESCENE"
            or channel.is_official is not True
            or video.video_id != "verification-video"
            or video.channel_id != "verification-channel"
            or video.title != "Verification Video"
            or video.description != "Verification description"
            or video.channel_title != "RESCENE"
            or video.tags != ["verification", "music"]
            or video.category_id != "10"
            or video.duration != "PT2M30S"
            or video.caption is not True
            or video.definition != "hd"
            or video.published_at.isoformat() != "2026-09-21T12:00:00"
            or metrics.video_id != "verification-video"
            or metrics.view_count != 10
            or metrics.like_count is not None
            or metrics.comment_count is not None
            or metrics.observed_at.isoformat() != "2026-09-22T01:23:45"
        ):
            raise SilverPersistenceError("Stored Silver values are incorrect.")
    finally:
        spark.stop()

    print(
        "Spark/Iceberg verification succeeded: 1 channel, 1 video, "
        "1 metrics snapshot after repeated write"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BronzeStorageError, SilverPersistenceError) as error:
        raise SystemExit(f"Error: {error}") from error
