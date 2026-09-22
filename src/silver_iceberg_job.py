"""Run the on-demand persisted Bronze-to-Silver Iceberg job."""

import sys

from bronze_storage import BronzeStorage, BronzeStorageError
from mvp_config import RESCENE_CHANNELS
from silver_iceberg import (
    SilverPersistenceError,
    build_spark_session,
    persist_silver_result,
)
from silver_transform import transform_from_minio


def main() -> int:
    storage = BronzeStorage.from_environment()
    storage.ensure_bucket()
    result = transform_from_minio(storage, RESCENE_CHANNELS)
    if result.invalid_records:
        for failure in result.invalid_records:
            print(
                f"Invalid Bronze record: {failure['source_reference']}: "
                f"{failure['error_message']}",
                file=sys.stderr,
            )
    spark = build_spark_session()
    try:
        persist_silver_result(spark, result)
    finally:
        spark.stop()
    if result.invalid_records:
        raise SilverPersistenceError(
            f"Persisted valid records, but Bronze-to-Silver produced "
            f"{len(result.invalid_records)} invalid record(s)."
        )
    print(
        "Silver Iceberg write succeeded: "
        f"{len(result.youtube_channels)} channel(s), "
        f"{len(result.youtube_videos)} video(s), "
        f"{len(result.video_metrics_snapshots)} metrics snapshot(s)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BronzeStorageError, SilverPersistenceError) as error:
        raise SystemExit(f"Error: {error}") from error
