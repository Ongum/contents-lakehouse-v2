"""Run the on-demand Silver Iceberg to Gold Iceberg job."""

from gold_iceberg import GoldPersistenceError, build_and_persist_gold
from silver_iceberg import SilverPersistenceError, build_spark_session


def main() -> int:
    spark = build_spark_session()
    try:
        frames = build_and_persist_gold(spark)
        hourly_count = frames.video_metrics_hourly.count()
        growth_count = frames.video_growth_24h.count()
    finally:
        spark.stop()
    print(
        "Gold Iceberg write succeeded: "
        f"{hourly_count} hourly row(s), {growth_count} 24-hour row(s)"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GoldPersistenceError, SilverPersistenceError) as error:
        raise SystemExit(f"Error: {error}") from error
