"""Persist canonical Silver records to Apache Iceberg with Spark."""

import os
import re
from datetime import datetime, timezone
from typing import Any


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SilverPersistenceError(Exception):
    """Raised when canonical Silver records cannot be persisted safely."""


def _environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SilverPersistenceError(f"Missing configuration: {name}.")
    return value


def _identifier(name: str, value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise SilverPersistenceError(f"Invalid {name}: {value!r}.")
    return value


def _utc_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise SilverPersistenceError(f"Invalid {field_name} timestamp.") from error
    if parsed.tzinfo is None:
        raise SilverPersistenceError(f"{field_name} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def build_spark_session() -> Any:
    """Create the short-lived local Spark session used for Silver writes."""
    try:
        from pyspark.sql import SparkSession
    except ImportError as error:
        raise SilverPersistenceError(
            "PySpark is required; run this job with the Spark Compose profile."
        ) from error

    catalog = _identifier(
        "ICEBERG_CATALOG", os.environ.get("ICEBERG_CATALOG", "lakehouse")
    )
    warehouse = _environment("ICEBERG_WAREHOUSE")
    endpoint = _environment("MINIO_ENDPOINT")
    access_key = _environment("MINIO_ACCESS_KEY")
    secret_key = _environment("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("rescene-silver-iceberg")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.defaultCatalog", "spark_catalog")
        .config(
            f"spark.sql.catalog.{catalog}",
            "org.apache.iceberg.spark.SparkCatalog",
        )
        .config(f"spark.sql.catalog.{catalog}.type", "hadoop")
        .config(f"spark.sql.catalog.{catalog}.warehouse", warehouse)
        .config(
            f"spark.sql.catalog.{catalog}.io-impl",
            "org.apache.iceberg.aws.s3.S3FileIO",
        )
        .config(f"spark.sql.catalog.{catalog}.s3.endpoint", endpoint)
        .config(f"spark.sql.catalog.{catalog}.s3.path-style-access", "true")
        .config(f"spark.sql.catalog.{catalog}.s3.access-key-id", access_key)
        .config(f"spark.sql.catalog.{catalog}.s3.secret-access-key", secret_key)
        .config(f"spark.sql.catalog.{catalog}.client.region", "us-east-1")
        .config("spark.hadoop.fs.s3a.endpoint", endpoint)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.access.key", access_key)
        .config("spark.hadoop.fs.s3a.secret.key", secret_key)
        .config(
            "spark.hadoop.fs.s3a.aws.credentials.provider",
            "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider",
        )
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def _table_names() -> tuple[str, str]:
    catalog = _identifier(
        "ICEBERG_CATALOG", os.environ.get("ICEBERG_CATALOG", "lakehouse")
    )
    namespace = _identifier(
        "SILVER_NAMESPACE", os.environ.get("SILVER_NAMESPACE", "silver")
    )
    return catalog, namespace


def create_silver_tables(spark: Any) -> None:
    catalog, namespace = _table_names()
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
    definitions = {
        "youtube_channel": """
            channel_id STRING NOT NULL,
            artist_id STRING NOT NULL,
            channel_title STRING NOT NULL,
            is_official BOOLEAN NOT NULL,
            source_updated_at TIMESTAMP
        """,
        "youtube_video": """
            video_id STRING NOT NULL,
            channel_id STRING NOT NULL,
            title STRING NOT NULL,
            published_at TIMESTAMP NOT NULL,
            source_updated_at TIMESTAMP
        """,
        "video_metrics_snapshot": """
            video_id STRING NOT NULL,
            observed_at TIMESTAMP NOT NULL,
            view_count BIGINT NOT NULL,
            like_count BIGINT,
            comment_count BIGINT
        """,
    }
    for table, columns in definitions.items():
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table} "
            f"({columns}) USING iceberg "
            "TBLPROPERTIES ('format-version' = '2')"
        )


def _merge(spark: Any, table: str, rows: list[dict[str, Any]], schema: Any) -> None:
    if not rows:
        return
    catalog, namespace = _table_names()
    view = f"incoming_{table}"
    spark.createDataFrame(rows, schema=schema).createOrReplaceTempView(view)
    keys = {
        "youtube_channel": "target.channel_id = source.channel_id",
        "youtube_video": "target.video_id = source.video_id",
        "video_metrics_snapshot": (
            "target.video_id = source.video_id "
            "AND target.observed_at = source.observed_at"
        ),
    }
    spark.sql(
        f"MERGE INTO {catalog}.{namespace}.{table} target "
        f"USING {view} source ON {keys[table]} "
        "WHEN MATCHED THEN UPDATE SET * "
        "WHEN NOT MATCHED THEN INSERT *"
    )
    spark.catalog.dropTempView(view)


def persist_silver_result(spark: Any, result: Any) -> None:
    """Upsert one canonical SilverResult into the three MVP Iceberg tables."""
    from pyspark.sql.types import (
        BooleanType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    channel_schema = StructType(
        [
            StructField("channel_id", StringType(), False),
            StructField("artist_id", StringType(), False),
            StructField("channel_title", StringType(), False),
            StructField("is_official", BooleanType(), False),
            StructField("source_updated_at", TimestampType(), True),
        ]
    )
    video_schema = StructType(
        [
            StructField("video_id", StringType(), False),
            StructField("channel_id", StringType(), False),
            StructField("title", StringType(), False),
            StructField("published_at", TimestampType(), False),
            StructField("source_updated_at", TimestampType(), True),
        ]
    )
    metrics_schema = StructType(
        [
            StructField("video_id", StringType(), False),
            StructField("observed_at", TimestampType(), False),
            StructField("view_count", LongType(), False),
            StructField("like_count", LongType(), True),
            StructField("comment_count", LongType(), True),
        ]
    )

    channels = [dict(row) for row in result.youtube_channels]
    for row in channels:
        if row["source_updated_at"] is not None:
            row["source_updated_at"] = _utc_datetime(
                row["source_updated_at"], "source_updated_at"
            )
    videos = [dict(row) for row in result.youtube_videos]
    for row in videos:
        row["published_at"] = _utc_datetime(row["published_at"], "published_at")
        if row["source_updated_at"] is not None:
            row["source_updated_at"] = _utc_datetime(
                row["source_updated_at"], "source_updated_at"
            )
    snapshots = [dict(row) for row in result.video_metrics_snapshots]
    for row in snapshots:
        row["observed_at"] = _utc_datetime(row["observed_at"], "observed_at")

    create_silver_tables(spark)
    _merge(spark, "youtube_channel", channels, channel_schema)
    _merge(spark, "youtube_video", videos, video_schema)
    _merge(spark, "video_metrics_snapshot", snapshots, metrics_schema)
