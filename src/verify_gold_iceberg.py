"""Verify isolated Silver Iceberg to Gold Iceberg calculation and writes."""

import os

from bronze_storage import BronzeStorage
from gold_iceberg import build_and_persist_gold, gold_table_names
from silver_iceberg import build_spark_session, persist_silver_result
from silver_transform import SilverResult


def main() -> int:
    BronzeStorage.from_environment().ensure_bucket()
    result = SilverResult(
        video_metrics_snapshots=[
            {
                "video_id": "verification-video",
                "observed_at": "2026-01-01T00:00:00Z",
                "view_count": 100,
                "like_count": 10,
                "comment_count": None,
            },
            {
                "video_id": "verification-video",
                "observed_at": "2026-01-01T01:00:00Z",
                "view_count": 120,
                "like_count": None,
                "comment_count": 5,
            },
            {
                "video_id": "verification-video",
                "observed_at": "2026-01-02T01:30:00Z",
                "view_count": 150,
                "like_count": 12,
                "comment_count": 2,
            },
        ]
    )
    spark = build_spark_session()
    try:
        persist_silver_result(spark, result)
        persist_silver_result(spark, result)
        build_and_persist_gold(spark)
        build_and_persist_gold(spark)

        catalog, namespace = gold_table_names()
        hourly = spark.table(f"{catalog}.{namespace}.video_metrics_hourly")
        growth = spark.table(f"{catalog}.{namespace}.video_growth_24h")
        if hourly.count() != 3 or growth.count() != 3:
            raise RuntimeError("Repeated Gold write created duplicate rows.")

        hourly_rows = {row.observed_at.isoformat(): row for row in hourly.collect()}
        one_hour = hourly_rows["2026-01-01T01:00:00"]
        if (
            one_hour.view_delta != 20
            or one_hour.like_delta is not None
            or one_hour.comment_delta is not None
        ):
            raise RuntimeError("Hourly Gold metrics are incorrect.")

        growth_rows = {row.observed_at.isoformat(): row for row in growth.collect()}
        missing_hour = growth_rows["2026-01-02T01:30:00"]
        if (
            missing_hour.view_delta_24h != 30
            or missing_hour.like_delta_24h is not None
            or missing_hour.comment_delta_24h != -3
            or abs(missing_hour.view_growth_rate_24h - 0.25) > 1e-12
        ):
            raise RuntimeError("24-hour Gold metrics are incorrect.")

        silver_catalog = os.environ.get("ICEBERG_CATALOG", "lakehouse")
        silver_namespace = os.environ.get("SILVER_NAMESPACE", "silver")
        if spark.table(
            f"{silver_catalog}.{silver_namespace}.video_metrics_snapshot"
        ).count() != 3:
            raise RuntimeError("Silver input was unexpectedly modified.")
    finally:
        spark.stop()

    print(
        "Silver-to-Gold Iceberg verification succeeded: "
        "3 hourly rows and 3 24-hour rows after repeated writes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
