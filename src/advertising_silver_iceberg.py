"""Persist canonical advertising Silver records to Iceberg."""

from datetime import date
from typing import Any

if __package__:
    from .silver_iceberg import _table_names, _utc_datetime
else:
    from silver_iceberg import _table_names, _utc_datetime


TABLE_DEFINITIONS = {
    "advertiser_organization": """
        organization_id STRING NOT NULL,
        organization_name STRING NOT NULL
    """,
    "brand": """
        brand_id STRING NOT NULL,
        brand_name STRING NOT NULL,
        organization_id STRING
    """,
    "product": """
        product_id STRING NOT NULL,
        brand_id STRING NOT NULL,
        product_name STRING NOT NULL,
        source_category_text STRING
    """,
    "product_category": """
        category_id STRING NOT NULL,
        source_category_text STRING NOT NULL
    """,
    "advertising_campaign": """
        campaign_id STRING NOT NULL,
        campaign_name STRING,
        relationship_type STRING NOT NULL,
        announced_at TIMESTAMP,
        campaign_start_date DATE,
        campaign_end_date DATE,
        status STRING
    """,
    "campaign_artist": """
        campaign_artist_id STRING NOT NULL,
        campaign_id STRING NOT NULL,
        artist_id STRING NOT NULL,
        participation_role STRING
    """,
    "campaign_product": """
        campaign_product_id STRING NOT NULL,
        campaign_id STRING NOT NULL,
        product_id STRING NOT NULL
    """,
    "campaign_source": """
        campaign_id STRING NOT NULL,
        source_type STRING NOT NULL,
        source_name STRING NOT NULL,
        source_url STRING NOT NULL,
        source_identifier STRING NOT NULL,
        bronze_object_reference STRING NOT NULL,
        content_hash STRING NOT NULL,
        retrieved_at TIMESTAMP NOT NULL,
        published_at DATE,
        collector_version STRING NOT NULL
    """,
    "campaign_market_metric": """
        metric_id STRING NOT NULL,
        campaign_id STRING,
        product_id STRING,
        metric_type STRING NOT NULL,
        value DOUBLE NOT NULL,
        unit STRING NOT NULL,
        measurement_start DATE,
        measurement_end DATE,
        observed_at TIMESTAMP NOT NULL,
        comparison_type STRING,
        comparison_start DATE,
        comparison_end DATE,
        channel STRING,
        scope STRING,
        asset_reference STRING,
        reported_by STRING,
        is_company_reported BOOLEAN NOT NULL,
        source_reference STRING NOT NULL,
        attribution_note STRING
    """,
}


def create_advertising_silver_tables(spark: Any) -> None:
    catalog, namespace = _table_names()
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
    for table, columns in TABLE_DEFINITIONS.items():
        spark.sql(
            f"CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table} "
            f"({columns}) USING iceberg TBLPROPERTIES ('format-version' = '2')"
        )


def _merge_advertising(
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


def persist_advertising_silver_result(spark: Any, result: Any) -> None:
    from pyspark.sql.types import (
        BooleanType,
        DateType,
        DoubleType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    schemas = {
        "advertiser_organization": StructType(
            [
                StructField("organization_id", StringType(), False),
                StructField("organization_name", StringType(), False),
            ]
        ),
        "brand": StructType(
            [
                StructField("brand_id", StringType(), False),
                StructField("brand_name", StringType(), False),
                StructField("organization_id", StringType(), True),
            ]
        ),
        "product": StructType(
            [
                StructField("product_id", StringType(), False),
                StructField("brand_id", StringType(), False),
                StructField("product_name", StringType(), False),
                StructField("source_category_text", StringType(), True),
            ]
        ),
        "product_category": StructType(
            [
                StructField("category_id", StringType(), False),
                StructField("source_category_text", StringType(), False),
            ]
        ),
        "advertising_campaign": StructType(
            [
                StructField("campaign_id", StringType(), False),
                StructField("campaign_name", StringType(), True),
                StructField("relationship_type", StringType(), False),
                StructField("announced_at", TimestampType(), True),
                StructField("campaign_start_date", DateType(), True),
                StructField("campaign_end_date", DateType(), True),
                StructField("status", StringType(), True),
            ]
        ),
        "campaign_artist": StructType(
            [
                StructField("campaign_artist_id", StringType(), False),
                StructField("campaign_id", StringType(), False),
                StructField("artist_id", StringType(), False),
                StructField("participation_role", StringType(), True),
            ]
        ),
        "campaign_product": StructType(
            [
                StructField("campaign_product_id", StringType(), False),
                StructField("campaign_id", StringType(), False),
                StructField("product_id", StringType(), False),
            ]
        ),
        "campaign_source": StructType(
            [
                StructField("campaign_id", StringType(), False),
                StructField("source_type", StringType(), False),
                StructField("source_name", StringType(), False),
                StructField("source_url", StringType(), False),
                StructField("source_identifier", StringType(), False),
                StructField("bronze_object_reference", StringType(), False),
                StructField("content_hash", StringType(), False),
                StructField("retrieved_at", TimestampType(), False),
                StructField("published_at", DateType(), True),
                StructField("collector_version", StringType(), False),
            ]
        ),
        "campaign_market_metric": StructType(
            [
                StructField("metric_id", StringType(), False),
                StructField("campaign_id", StringType(), True),
                StructField("product_id", StringType(), True),
                StructField("metric_type", StringType(), False),
                StructField("value", DoubleType(), False),
                StructField("unit", StringType(), False),
                StructField("measurement_start", DateType(), True),
                StructField("measurement_end", DateType(), True),
                StructField("observed_at", TimestampType(), False),
                StructField("comparison_type", StringType(), True),
                StructField("comparison_start", DateType(), True),
                StructField("comparison_end", DateType(), True),
                StructField("channel", StringType(), True),
                StructField("scope", StringType(), True),
                StructField("asset_reference", StringType(), True),
                StructField("reported_by", StringType(), True),
                StructField("is_company_reported", BooleanType(), False),
                StructField("source_reference", StringType(), False),
                StructField("attribution_note", StringType(), True),
            ]
        ),
    }
    rows = {
        "advertiser_organization": [dict(row) for row in result.organizations],
        "brand": [dict(row) for row in result.brands],
        "product": [dict(row) for row in result.products],
        "product_category": [dict(row) for row in result.product_categories],
        "advertising_campaign": [dict(row) for row in result.campaigns],
        "campaign_artist": [dict(row) for row in result.campaign_artists],
        "campaign_product": [dict(row) for row in result.campaign_products],
        "campaign_source": [dict(row) for row in result.campaign_sources],
        "campaign_market_metric": [dict(row) for row in result.market_metrics],
    }
    for row in rows["advertising_campaign"]:
        if row["announced_at"] is not None:
            row["announced_at"] = _utc_datetime(row["announced_at"], "announced_at")
        for field in ("campaign_start_date", "campaign_end_date"):
            if row[field] is not None:
                row[field] = date.fromisoformat(row[field])
    for row in rows["campaign_source"]:
        row["retrieved_at"] = _utc_datetime(row["retrieved_at"], "retrieved_at")
        if row["published_at"] is not None:
            row["published_at"] = date.fromisoformat(row["published_at"])
    for row in rows["campaign_market_metric"]:
        row["observed_at"] = _utc_datetime(row["observed_at"], "observed_at")
        for field in (
            "measurement_start",
            "measurement_end",
            "comparison_start",
            "comparison_end",
        ):
            if row[field] is not None:
                row[field] = date.fromisoformat(row[field])

    create_advertising_silver_tables(spark)
    conditions = {
        "advertiser_organization": "target.organization_id = source.organization_id",
        "brand": "target.brand_id = source.brand_id",
        "product": "target.product_id = source.product_id",
        "product_category": "target.category_id = source.category_id",
        "advertising_campaign": "target.campaign_id = source.campaign_id",
        "campaign_artist": "target.campaign_artist_id = source.campaign_artist_id",
        "campaign_product": "target.campaign_product_id = source.campaign_product_id",
        "campaign_source": (
            "target.campaign_id = source.campaign_id AND "
            "target.bronze_object_reference = source.bronze_object_reference"
        ),
        "campaign_market_metric": "target.metric_id = source.metric_id",
    }
    for table in rows:
        _merge_advertising(spark, table, rows[table], schemas[table], conditions[table])
