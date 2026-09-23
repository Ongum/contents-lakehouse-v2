"""Print a compact inspection of persisted Silver and Gold Iceberg data."""

import os
import sys

from gold_iceberg import GoldPersistenceError, gold_table_names
from silver_iceberg import SilverPersistenceError, build_spark_session


def _short(value: object, limit: int = 72) -> str:
    if value is None:
        return "-"
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _format_duration_seconds(value: float | None) -> str:
    if value is None:
        return "unavailable"
    seconds = int(round(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}"


def main() -> int:
    from pyspark.sql import Window, functions as functions

    spark = build_spark_session()
    try:
        catalog = os.environ.get("ICEBERG_CATALOG", "lakehouse")
        namespace = os.environ.get("SILVER_NAMESPACE", "silver")
        channels = spark.table(f"{catalog}.{namespace}.youtube_channel")
        videos = spark.table(f"{catalog}.{namespace}.youtube_video")
        snapshots = spark.table(f"{catalog}.{namespace}.video_metrics_snapshot")

        print("Silver")
        print(f"  Channels: {channels.count()}")
        print(f"  Videos: {videos.count()}")
        print(f"  Metric snapshots: {snapshots.count()}")
        metric_availability = snapshots.agg(
            functions.count("like_count").alias("like_count"),
            functions.count("comment_count").alias("comment_count"),
        ).first()
        print(
            "  Nullable metrics populated: "
            f"likes={metric_availability.like_count:,}, "
            f"comments={metric_availability.comment_count:,}"
        )
        print("  Videos by channel title:")
        for row in videos.groupBy("channel_title").count().orderBy(
            functions.col("count").desc()
        ).collect():
            print(f"    {row['count']:,} | {_short(row.channel_title)}")
        metadata = videos.agg(
            *[
                functions.count(field).alias(field)
                for field in (
                    "description",
                    "channel_title",
                    "tags",
                    "category_id",
                    "duration",
                    "caption",
                    "definition",
                )
            ]
        ).first()
        print(
            "  Metadata populated: "
            + ", ".join(
                f"{field}={metadata[field]:,}"
                for field in (
                    "description",
                    "channel_title",
                    "tags",
                    "category_id",
                    "duration",
                    "caption",
                    "definition",
                )
            )
        )
        print("  Newest videos:")
        for row in videos.orderBy(functions.col("published_at").desc()).limit(5).collect():
            print(f"    {row.published_at} | {_short(row.title)} | {row.video_id}")

        latest_window = Window.partitionBy("video_id").orderBy(
            functions.col("observed_at").desc()
        )
        current = (
            snapshots.withColumn("rank", functions.row_number().over(latest_window))
            .where(functions.col("rank") == 1)
            .drop("rank")
        )
        video_current = videos.join(current, "video_id", "left")
        print("  Top videos by current views:")
        for row in (
            video_current.orderBy(functions.col("view_count").desc())
            .limit(5)
            .collect()
        ):
            print(
                f"    {row.view_count:,} | {_short(row.title)} | "
                f"observed {row.observed_at}"
            )

        print("Video sample")
        print("  Categories:")
        for row in videos.groupBy("category_id").count().orderBy(
            functions.col("count").desc(), functions.col("category_id")
        ).collect():
            print(f"    {_short(row.category_id)}: {row['count']:,} video(s)")

        duration_seconds = (
            functions.coalesce(
                functions.regexp_extract("duration", r"P(\d+)D", 1).cast("double"),
                functions.lit(0.0),
            )
            * 86400
            + functions.coalesce(
                functions.regexp_extract("duration", r"T(\d+)H", 1).cast("double"),
                functions.lit(0.0),
            )
            * 3600
            + functions.coalesce(
                functions.regexp_extract("duration", r"(?:T|H)(\d+)M", 1).cast(
                    "double"
                ),
                functions.lit(0.0),
            )
            * 60
            + functions.coalesce(
                functions.regexp_extract(
                    "duration", r"(?:T|M)([0-9]+(?:\.[0-9]+)?)S", 1
                ).cast("double"),
                functions.lit(0.0),
            )
        )
        duration_stats = (
            videos.where(functions.col("duration").isNotNull())
            .withColumn("duration_seconds", duration_seconds)
            .agg(
                functions.count("duration_seconds").alias("count"),
                functions.min("duration_seconds").alias("minimum"),
                functions.avg("duration_seconds").alias("average"),
                functions.max("duration_seconds").alias("maximum"),
            )
            .first()
        )
        print(
            "  Duration statistics: "
            f"count={duration_stats['count']:,}, "
            f"min={_format_duration_seconds(duration_stats.minimum)}, "
            f"avg={_format_duration_seconds(duration_stats.average)}, "
            f"max={_format_duration_seconds(duration_stats.maximum)}"
        )

        print("  Top 10 videos by likes:")
        for row in (
            video_current.where(functions.col("like_count").isNotNull())
            .orderBy(functions.col("like_count").desc())
            .limit(10)
            .collect()
        ):
            print(f"    {row.like_count:,} | {_short(row.title)} | {row.video_id}")

        print("  Top 10 videos by comments:")
        for row in (
            video_current.where(functions.col("comment_count").isNotNull())
            .orderBy(functions.col("comment_count").desc())
            .limit(10)
            .collect()
        ):
            print(
                f"    {row.comment_count:,} | {_short(row.title)} | {row.video_id}"
            )

        print("  20 recent videos:")
        for row in (
            video_current.orderBy(functions.col("published_at").desc())
            .limit(20)
            .collect()
        ):
            print(
                f"    {row.published_at} | {row.video_id} | "
                f"{_short(row.channel_title, 24)} | {_short(row.title, 48)} | "
                f"category={_short(row.category_id)} | duration={_short(row.duration)} | "
                f"views={row.view_count:,} | likes={_short(row.like_count)} | "
                f"comments={_short(row.comment_count)} | tags={_short(row.tags, 56)}"
            )

        gold_catalog, gold_namespace = gold_table_names()
        hourly = spark.table(f"{gold_catalog}.{gold_namespace}.video_metrics_hourly")
        growth = spark.table(f"{gold_catalog}.{gold_namespace}.video_growth_24h")
        print("Gold")
        print(f"  Hourly metric rows: {hourly.count()}")
        print(f"  24h growth rows: {growth.count()}")
        print("  Latest observations:")
        for row in (
            hourly.orderBy(functions.col("observed_at").desc(), "video_id")
            .limit(5)
            .collect()
        ):
            print(
                f"    {row.observed_at} | {row.video_id} | views {row.view_count:,}"
            )

        available_hourly = hourly.where(functions.col("view_delta").isNotNull())
        if available_hourly.limit(1).count() == 0:
            print("  View deltas: unavailable; more than one observation is required")
        else:
            print("  Top view deltas:")
            for row in available_hourly.orderBy(
                functions.col("view_delta").desc()
            ).limit(5).collect():
                print(f"    {row.view_delta:+,} | {row.video_id} | {row.observed_at}")

        available_24h = growth.where(functions.col("view_delta_24h").isNotNull())
        if available_24h.limit(1).count() == 0:
            print("  24h view deltas: unavailable; at least 24h history is required")
        else:
            print("  Top 24h view deltas:")
            for row in available_24h.orderBy(
                functions.col("view_delta_24h").desc()
            ).limit(5).collect():
                print(
                    f"    {row.view_delta_24h:+,} | {row.video_id} | "
                    f"{row.observed_at}"
                )
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GoldPersistenceError, SilverPersistenceError) as error:
        print(f"Inspection failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
