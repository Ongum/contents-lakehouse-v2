"""Run the current RESCENE YouTube MVP from API through Gold Iceberg."""

import sys
from uuid import uuid4

from bronze_storage import BronzeStorage, BronzeStorageError
from gold_iceberg import GoldPersistenceError, build_and_persist_gold, gold_table_names
from mvp_config import RESCENE_CHANNELS
from silver_iceberg import (
    SilverPersistenceError,
    build_spark_session,
    persist_silver_result,
)
from silver_transform import transform_bronze_objects
from youtube_connectivity import (
    BronzeCapture,
    ConnectivityError,
    collect_seed_videos,
    get_api_key,
    utc_now,
)


class PipelineError(Exception):
    """Raised when one end-to-end pipeline stage cannot complete safely."""


def main() -> int:
    run_id = str(uuid4())
    observed_at = utc_now()
    api_key = get_api_key()
    storage = BronzeStorage.from_environment()
    storage.ensure_bucket()

    capture = BronzeCapture(
        run_id=run_id,
        observed_at=observed_at,
        record_sink=storage.write_record,
    )
    collect_seed_videos(api_key, capture)
    persisted = [
        item for item in storage.list_records() if item[1].get("run_id") == run_id
    ]
    if len(persisted) != len(capture.records):
        raise PipelineError(
            "Persisted Bronze object count does not match captured API responses."
        )

    silver = transform_bronze_objects(persisted, RESCENE_CHANNELS)
    spark = build_spark_session()
    try:
        persist_silver_result(spark, silver)
        if silver.invalid_records:
            raise PipelineError(
                f"Silver transformation produced {len(silver.invalid_records)} "
                "invalid record(s); Gold was not updated."
            )
        build_and_persist_gold(spark)
        gold_catalog, gold_namespace = gold_table_names()
        gold_hourly_count = spark.table(
            f"{gold_catalog}.{gold_namespace}.video_metrics_hourly"
        ).count()
        gold_growth_count = spark.table(
            f"{gold_catalog}.{gold_namespace}.video_growth_24h"
        ).count()
    finally:
        spark.stop()

    print("RESCENE pipeline succeeded")
    print(f"Run ID: {run_id}")
    print(f"Observed at (UTC): {observed_at}")
    print(f"Bronze objects: {len(persisted)}")
    print(f"Silver channels in run: {len(silver.youtube_channels)}")
    print(f"Silver videos in run: {len(silver.youtube_videos)}")
    print(f"Silver metric snapshots in run: {len(silver.video_metrics_snapshots)}")
    print(f"Invalid records: {len(silver.invalid_records)}")
    print("Silver write: succeeded")
    print(
        "Gold write: succeeded "
        f"({gold_hourly_count} hourly rows, {gold_growth_count} 24h rows total)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        BronzeStorageError,
        ConnectivityError,
        GoldPersistenceError,
        PipelineError,
        SilverPersistenceError,
    ) as error:
        print(f"Pipeline failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
