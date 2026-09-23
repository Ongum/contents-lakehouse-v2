"""Persist canonical MediaWiki-derived Silver records to Iceberg."""

from datetime import date
from typing import Any

if __package__:
    from .silver_iceberg import _table_names, _utc_datetime
else:
    from silver_iceberg import _table_names, _utc_datetime


def create_mediawiki_silver_tables(spark: Any) -> None:
    catalog, namespace = _table_names()
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
    definitions = {
        "artist": """
            artist_id STRING NOT NULL,
            artist_name STRING NOT NULL,
            artist_type STRING NOT NULL
        """,
        "artist_external_identifier": """
            artist_id STRING NOT NULL,
            source_system STRING NOT NULL,
            external_id STRING NOT NULL,
            source_url STRING
        """,
        "artist_relationship": """
            relationship_id STRING NOT NULL,
            from_artist_id STRING NOT NULL,
            to_artist_id STRING NOT NULL,
            relationship_type STRING NOT NULL,
            start_date DATE,
            end_date DATE,
            source_name STRING,
            source_url STRING
        """,
        "artist_event": """
            event_id STRING NOT NULL,
            event_type STRING NOT NULL,
            event_name STRING NOT NULL,
            start_at TIMESTAMP,
            start_precision STRING,
            end_at TIMESTAMP,
            end_precision STRING,
            source_name STRING,
            source_url STRING
        """,
        "event_artist": """
            event_id STRING NOT NULL,
            artist_id STRING NOT NULL,
            participation_role STRING
        """,
        "mediawiki_lineage": """
            record_type STRING NOT NULL,
            record_key STRING NOT NULL,
            edition STRING NOT NULL,
            page_id BIGINT NOT NULL,
            revision_id BIGINT NOT NULL,
            source_reference STRING NOT NULL
        """,
    }
    for table, columns in definitions.items():
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table} "
            f"({columns}) USING iceberg TBLPROPERTIES ('format-version' = '2')"
        )


def _merge_mediawiki(
    spark: Any, table: str, rows: list[dict[str, Any]], schema: Any, condition: str
) -> None:
    if not rows:
        return
    catalog, namespace = _table_names()
    view = f"incoming_{table}"
    spark.createDataFrame(rows, schema=schema).createOrReplaceTempView(view)
    columns = [field.name for field in schema.fields]
    assignments = ", ".join(
        f"target.{column} = source.{column}" for column in columns
    )
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"source.{column}" for column in columns)
    spark.sql(
        f"MERGE INTO {catalog}.{namespace}.{table} target "
        f"USING {view} source ON {condition} "
        f"WHEN MATCHED THEN UPDATE SET {assignments} "
        f"WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})"
    )
    spark.catalog.dropTempView(view)


def persist_mediawiki_silver_result(spark: Any, result: Any) -> None:
    from pyspark.sql.types import (
        DateType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    schemas = {
        "artist": StructType(
            [
                StructField("artist_id", StringType(), False),
                StructField("artist_name", StringType(), False),
                StructField("artist_type", StringType(), False),
            ]
        ),
        "artist_external_identifier": StructType(
            [
                StructField("artist_id", StringType(), False),
                StructField("source_system", StringType(), False),
                StructField("external_id", StringType(), False),
                StructField("source_url", StringType(), True),
            ]
        ),
        "artist_relationship": StructType(
            [
                StructField("relationship_id", StringType(), False),
                StructField("from_artist_id", StringType(), False),
                StructField("to_artist_id", StringType(), False),
                StructField("relationship_type", StringType(), False),
                StructField("start_date", DateType(), True),
                StructField("end_date", DateType(), True),
                StructField("source_name", StringType(), True),
                StructField("source_url", StringType(), True),
            ]
        ),
        "artist_event": StructType(
            [
                StructField("event_id", StringType(), False),
                StructField("event_type", StringType(), False),
                StructField("event_name", StringType(), False),
                StructField("start_at", TimestampType(), True),
                StructField("start_precision", StringType(), True),
                StructField("end_at", TimestampType(), True),
                StructField("end_precision", StringType(), True),
                StructField("source_name", StringType(), True),
                StructField("source_url", StringType(), True),
            ]
        ),
        "event_artist": StructType(
            [
                StructField("event_id", StringType(), False),
                StructField("artist_id", StringType(), False),
                StructField("participation_role", StringType(), True),
            ]
        ),
        "mediawiki_lineage": StructType(
            [
                StructField("record_type", StringType(), False),
                StructField("record_key", StringType(), False),
                StructField("edition", StringType(), False),
                StructField("page_id", LongType(), False),
                StructField("revision_id", LongType(), False),
                StructField("source_reference", StringType(), False),
            ]
        ),
    }
    rows = {
        "artist": [dict(row) for row in result.artists],
        "artist_external_identifier": [
            dict(row) for row in result.artist_external_identifiers
        ],
        "artist_relationship": [dict(row) for row in result.artist_relationships],
        "artist_event": [dict(row) for row in result.artist_events],
        "event_artist": [dict(row) for row in result.event_artists],
        "mediawiki_lineage": [dict(row) for row in result.lineage],
    }
    for row in rows["artist_relationship"]:
        for field in ("start_date", "end_date"):
            if row[field] is not None:
                row[field] = date.fromisoformat(row[field])
    for row in rows["artist_event"]:
        for field in ("start_at", "end_at"):
            if row[field] is not None:
                row[field] = _utc_datetime(row[field], field)

    create_mediawiki_silver_tables(spark)
    conditions = {
        "artist": "target.artist_id = source.artist_id",
        "artist_external_identifier": (
            "target.artist_id = source.artist_id AND "
            "target.source_system = source.source_system AND "
            "target.external_id = source.external_id"
        ),
        "artist_relationship": (
            "target.relationship_id = source.relationship_id"
        ),
        "artist_event": "target.event_id = source.event_id",
        "event_artist": (
            "target.event_id = source.event_id AND "
            "target.artist_id = source.artist_id"
        ),
        "mediawiki_lineage": (
            "target.record_type = source.record_type AND "
            "target.record_key = source.record_key AND "
            "target.revision_id = source.revision_id"
        ),
    }
    for table in rows:
        _merge_mediawiki(spark, table, rows[table], schemas[table], conditions[table])
