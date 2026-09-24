"""Persist the additive artist activity timeline projection to Silver Iceberg."""

from typing import Any

if __package__:
    from .artist_activity_timeline import validate_artist_activity_timeline
    from .silver_iceberg import _table_names, _utc_datetime
else:
    from artist_activity_timeline import validate_artist_activity_timeline
    from silver_iceberg import _table_names, _utc_datetime


def create_artist_activity_timeline_tables(spark: Any) -> None:
    catalog, namespace = _table_names()
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.artist_activity_timeline ("
        "timeline_event_id STRING NOT NULL, artist_id STRING NOT NULL, "
        "event_type STRING NOT NULL, event_name STRING NOT NULL, "
        "event_at TIMESTAMP NOT NULL, temporal_precision STRING NOT NULL, "
        "time_semantics STRING NOT NULL, observed_at TIMESTAMP, "
        "source_domain STRING NOT NULL, source_entity_type STRING NOT NULL, "
        "source_entity_id STRING NOT NULL, source_reference STRING"
        ") USING iceberg TBLPROPERTIES ('format-version' = '2')"
    )
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.artist_activity_timeline_evidence ("
        "timeline_event_id STRING NOT NULL, source_evidence_id STRING NOT NULL"
        ") USING iceberg TBLPROPERTIES ('format-version' = '2')"
    )


def _merge(
    spark: Any, table: str, rows: list[dict[str, Any]], schema: Any, condition: str
) -> None:
    if not rows:
        return
    catalog, namespace = _table_names()
    view = f"incoming_{table}"
    spark.createDataFrame(rows, schema=schema).createOrReplaceTempView(view)
    columns = [field.name for field in schema.fields]
    assignments = ", ".join(f"target.{name} = source.{name}" for name in columns)
    spark.sql(
        f"MERGE INTO {catalog}.{namespace}.{table} target USING {view} source "
        f"ON {condition} WHEN MATCHED THEN UPDATE SET {assignments} "
        f"WHEN NOT MATCHED THEN INSERT ({', '.join(columns)}) VALUES "
        f"({', '.join(f'source.{name}' for name in columns)})"
    )
    spark.catalog.dropTempView(view)


def persist_artist_activity_timeline(
    spark: Any, result: Any, artist_ids: list[str]
) -> None:
    validate_artist_activity_timeline(result, artist_ids)
    _validate_source_evidence_references(spark, result)

    from pyspark.sql.types import StringType, StructField, StructType, TimestampType

    event_schema = StructType(
        [
            StructField("timeline_event_id", StringType(), False),
            StructField("artist_id", StringType(), False),
            StructField("event_type", StringType(), False),
            StructField("event_name", StringType(), False),
            StructField("event_at", TimestampType(), False),
            StructField("temporal_precision", StringType(), False),
            StructField("time_semantics", StringType(), False),
            StructField("observed_at", TimestampType(), True),
            StructField("source_domain", StringType(), False),
            StructField("source_entity_type", StringType(), False),
            StructField("source_entity_id", StringType(), False),
            StructField("source_reference", StringType(), True),
        ]
    )
    evidence_schema = StructType(
        [
            StructField("timeline_event_id", StringType(), False),
            StructField("source_evidence_id", StringType(), False),
        ]
    )
    events = [dict(row) for row in result.events]
    for row in events:
        row["event_at"] = _utc_datetime(row["event_at"], "event_at")
        if row["observed_at"] is not None:
            row["observed_at"] = _utc_datetime(row["observed_at"], "observed_at")
    create_artist_activity_timeline_tables(spark)
    _merge(
        spark,
        "artist_activity_timeline",
        events,
        event_schema,
        "target.timeline_event_id = source.timeline_event_id",
    )
    _merge(
        spark,
        "artist_activity_timeline_evidence",
        [dict(row) for row in result.event_evidence],
        evidence_schema,
        "target.timeline_event_id = source.timeline_event_id AND "
        "target.source_evidence_id = source.source_evidence_id",
    )


def _validate_source_evidence_references(spark: Any, result: Any) -> None:
    """Reject timeline evidence links absent from canonical Silver evidence."""
    referenced = {
        row["source_evidence_id"] for row in result.event_evidence
    }
    if not referenced:
        return
    catalog, namespace = _table_names()
    canonical = {
        row.source_evidence_id
        for row in spark.table(
            f"{catalog}.{namespace}.source_evidence"
        ).select("source_evidence_id").collect()
    }
    missing = referenced - canonical
    if missing:
        raise ValueError(
            "Timeline evidence references missing canonical source_evidence."
        )
