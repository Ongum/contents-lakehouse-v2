"""Verify real MediaWiki Bronze-to-Silver transformation and Iceberg writes."""

import os

from bronze_storage import BronzeStorageError
from mediawiki_bronze import MediaWikiBronzeStorage
from mediawiki_silver import MediaWikiTransformError, transform_latest_from_minio
from mediawiki_silver_iceberg import persist_mediawiki_silver_result
from mvp_config import RESCENE_ARTIST_ID
from silver_iceberg import SilverPersistenceError, build_spark_session


def main() -> int:
    storage = MediaWikiBronzeStorage.from_environment()
    storage.ensure_bucket()
    result = transform_latest_from_minio(storage)
    if result.invalid_records:
        raise MediaWikiTransformError(result.invalid_records[0]["error_message"])

    spark = build_spark_session()
    try:
        persist_mediawiki_silver_result(spark, result)
        persist_mediawiki_silver_result(spark, result)
        catalog = os.environ.get("ICEBERG_CATALOG", "lakehouse")
        namespace = os.environ.get("SILVER_NAMESPACE", "silver")
        prefix = f"{catalog}.{namespace}"
        artist_ids = [row["artist_id"] for row in result.artists]
        relationship_ids = [
            row["relationship_id"] for row in result.artist_relationships
        ]
        event_ids = [row["event_id"] for row in result.artist_events]

        artists = spark.table(f"{prefix}.artist")
        relationships = spark.table(f"{prefix}.artist_relationship")
        events = spark.table(f"{prefix}.artist_event")
        event_artists = spark.table(f"{prefix}.event_artist")
        artist_count = artists.filter(artists.artist_id.isin(artist_ids)).count()
        relationship_count = relationships.filter(
            relationships.relationship_id.isin(relationship_ids)
        ).count()
        event_count = events.filter(events.event_id.isin(event_ids)).count()
        link_count = event_artists.filter(
            (event_artists.artist_id == RESCENE_ARTIST_ID)
            & event_artists.event_id.isin(event_ids)
        ).count()
        if (
            artist_count != 6
            or relationship_count != 5
            or event_count != len(result.artist_events)
            or link_count != len(result.artist_events)
            or not any(row["event_name"] == "Re:Scene" for row in result.artist_events)
        ):
            raise SilverPersistenceError("MediaWiki Silver verification failed.")
    finally:
        spark.stop()

    print("MediaWiki Bronze-to-Silver verification succeeded.")
    print("Artists: " + ", ".join(row["artist_name"] for row in result.artists))
    print(f"MEMBER_OF relationships: {len(result.artist_relationships)}")
    print(f"Release events: {len(result.artist_events)}")
    for event in result.artist_events:
        print(
            f"- {event['event_name']}: {event['start_at'][:10]} "
            f"({event['start_precision']})"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        BronzeStorageError,
        MediaWikiTransformError,
        SilverPersistenceError,
    ) as error:
        raise SystemExit(f"Error: {error}") from error
