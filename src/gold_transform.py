"""Build generic YouTube time-series Gold metrics from Silver snapshots."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GoldFrames:
    video_metrics_hourly: Any
    video_growth_24h: Any


def calculate_gold_frames(snapshots: Any) -> GoldFrames:
    """Calculate deltas without rounding or inventing observation timestamps.

    The 24-hour baseline is the latest real observation at or before exactly
    24 hours before each current observation.
    """
    from pyspark.sql import Window, functions as functions

    columns = [
        "video_id",
        "observed_at",
        "view_count",
        "like_count",
        "comment_count",
    ]
    canonical = snapshots.select(*columns).dropDuplicates(
        ["video_id", "observed_at"]
    )
    previous = Window.partitionBy("video_id").orderBy("observed_at")
    hourly = canonical.select(
        *columns,
        (
            functions.col("view_count")
            - functions.lag("view_count").over(previous)
        ).alias("view_delta"),
        (
            functions.col("like_count")
            - functions.lag("like_count").over(previous)
        ).alias("like_delta"),
        (
            functions.col("comment_count")
            - functions.lag("comment_count").over(previous)
        ).alias("comment_delta"),
    )

    current = canonical.alias("current")
    historical = canonical.alias("historical")
    candidates = current.join(
        historical,
        (functions.col("current.video_id") == functions.col("historical.video_id"))
        & (
            functions.col("historical.observed_at")
            <= functions.col("current.observed_at")
            - functions.expr("INTERVAL 24 HOURS")
        ),
        "left",
    ).select(
        functions.col("current.video_id").alias("video_id"),
        functions.col("current.observed_at").alias("observed_at"),
        functions.col("current.view_count").alias("view_count"),
        functions.col("current.like_count").alias("current_like_count"),
        functions.col("current.comment_count").alias("current_comment_count"),
        functions.col("historical.observed_at").alias("historical_observed_at"),
        functions.col("historical.view_count").alias("historical_view_count"),
        functions.col("historical.like_count").alias("historical_like_count"),
        functions.col("historical.comment_count").alias(
            "historical_comment_count"
        ),
    )
    baseline = Window.partitionBy("video_id", "observed_at").orderBy(
        functions.col("historical_observed_at").desc_nulls_last()
    )
    selected = candidates.withColumn(
        "baseline_rank", functions.row_number().over(baseline)
    ).where(functions.col("baseline_rank") == 1)
    view_delta_24h = functions.col("view_count") - functions.col(
        "historical_view_count"
    )
    growth_24h = selected.select(
        "video_id",
        "observed_at",
        "view_count",
        view_delta_24h.alias("view_delta_24h"),
        (
            functions.col("current_like_count")
            - functions.col("historical_like_count")
        ).alias("like_delta_24h"),
        (
            functions.col("current_comment_count")
            - functions.col("historical_comment_count")
        ).alias("comment_delta_24h"),
        functions.when(
            functions.col("historical_view_count").isNull()
            | (functions.col("historical_view_count") == 0),
            functions.lit(None).cast("double"),
        )
        .otherwise(
            view_delta_24h.cast("double")
            / functions.col("historical_view_count").cast("double")
        )
        .alias("view_growth_rate_24h"),
    )
    return GoldFrames(hourly, growth_24h)
