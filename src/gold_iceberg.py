"""Persist YouTube time-series Gold metrics as Iceberg tables."""

import os
import re
from typing import Any

from gold_transform import GoldFrames, calculate_gold_frames


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GoldPersistenceError(Exception):
    """Raised when Gold calculation or persistence cannot complete."""


def _identifier(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    if not _IDENTIFIER.fullmatch(value):
        raise GoldPersistenceError(f"Invalid {name}: {value!r}.")
    return value


def gold_table_names() -> tuple[str, str]:
    return (
        _identifier("GOLD_ICEBERG_CATALOG", "gold_lakehouse"),
        _identifier("GOLD_NAMESPACE", "gold"),
    )


def silver_metrics_table() -> str:
    catalog = _identifier("ICEBERG_CATALOG", "lakehouse")
    namespace = _identifier("SILVER_NAMESPACE", "silver")
    return f"{catalog}.{namespace}.video_metrics_snapshot"


def create_gold_tables(spark: Any) -> None:
    catalog, namespace = gold_table_names()
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
    definitions = {
        "video_metrics_hourly": """
            video_id STRING NOT NULL,
            observed_at TIMESTAMP NOT NULL,
            view_count BIGINT NOT NULL,
            like_count BIGINT,
            comment_count BIGINT,
            view_delta BIGINT,
            like_delta BIGINT,
            comment_delta BIGINT
        """,
        "video_growth_24h": """
            video_id STRING NOT NULL,
            observed_at TIMESTAMP NOT NULL,
            view_count BIGINT NOT NULL,
            view_delta_24h BIGINT,
            like_delta_24h BIGINT,
            comment_delta_24h BIGINT,
            view_growth_rate_24h DOUBLE
        """,
    }
    for table, columns in definitions.items():
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table} "
            f"({columns}) USING iceberg "
            "TBLPROPERTIES ('format-version' = '2')"
        )


def _merge_frame(spark: Any, table: str, frame: Any) -> None:
    catalog, namespace = gold_table_names()
    view = f"incoming_{table}"
    frame.createOrReplaceTempView(view)
    spark.sql(
        f"MERGE INTO {catalog}.{namespace}.{table} target "
        f"USING {view} source "
        "ON target.video_id = source.video_id "
        "AND target.observed_at = source.observed_at "
        "WHEN MATCHED THEN UPDATE SET * "
        "WHEN NOT MATCHED THEN INSERT *"
    )
    spark.catalog.dropTempView(view)


def persist_gold_frames(spark: Any, frames: GoldFrames) -> None:
    create_gold_tables(spark)
    _merge_frame(spark, "video_metrics_hourly", frames.video_metrics_hourly)
    _merge_frame(spark, "video_growth_24h", frames.video_growth_24h)


def build_and_persist_gold(spark: Any) -> GoldFrames:
    """Read Silver Iceberg only, calculate Gold, and idempotently persist it."""
    snapshots = spark.table(silver_metrics_table())
    frames = calculate_gold_frames(snapshots)
    persist_gold_frames(spark, frames)
    return frames
