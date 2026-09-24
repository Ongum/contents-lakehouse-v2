"""Persist canonical advertising Silver records to Iceberg."""

from datetime import date
import re
from typing import Any

if __package__:
    from .advertising_silver import RELATIONSHIP_TYPES
    from .silver_iceberg import _table_names, _utc_datetime
else:
    from advertising_silver import RELATIONSHIP_TYPES
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
        category_name STRING NOT NULL,
        parent_category_id STRING,
        taxonomy_name STRING NOT NULL,
        taxonomy_version STRING NOT NULL,
        source_category_text STRING
    """,
    "product_category_assignment": """
        product_id STRING NOT NULL,
        category_id STRING NOT NULL
    """,
    "product_tag": """
        tag_id STRING NOT NULL,
        tag_name STRING NOT NULL,
        tag_type STRING,
        normalized_value STRING
    """,
    "product_tag_assignment": """
        product_id STRING NOT NULL,
        tag_id STRING NOT NULL,
        source_evidence_id STRING,
        observed_at TIMESTAMP
    """,
    "source_evidence": """
        source_evidence_id STRING NOT NULL,
        source_name STRING NOT NULL,
        source_type STRING NOT NULL,
        source_url STRING,
        source_record_id STRING,
        collected_at TIMESTAMP NOT NULL,
        published_at TIMESTAMP,
        content_hash STRING NOT NULL,
        authority_level STRING NOT NULL,
        raw_bronze_reference STRING NOT NULL,
        verification_status STRING NOT NULL
    """,
    "advertising_campaign": """
        campaign_id STRING NOT NULL,
        campaign_name STRING,
        relationship_type STRING,
        announced_at TIMESTAMP,
        campaign_start_date DATE,
        campaign_end_date DATE,
        status STRING
    """,
    "campaign_brand": """
        campaign_id STRING NOT NULL,
        brand_id STRING NOT NULL
    """,
    "advertisement_creative": """
        creative_id STRING NOT NULL,
        campaign_id STRING,
        brand_id STRING,
        product_id STRING,
        source_type STRING NOT NULL,
        source_creative_id STRING NOT NULL,
        creative_type STRING NOT NULL,
        title STRING,
        description STRING,
        media_url STRING,
        landing_url STRING,
        platform STRING,
        first_observed_at TIMESTAMP NOT NULL,
        last_observed_at TIMESTAMP NOT NULL,
        published_at TIMESTAMP,
        active_from TIMESTAMP,
        active_to TIMESTAMP,
        source_evidence_id STRING NOT NULL
    """,
    "creative_tag": """
        creative_tag_id STRING NOT NULL,
        tag_name STRING NOT NULL,
        tag_type STRING NOT NULL,
        normalized_value STRING,
        source_native_value STRING
    """,
    "creative_tag_assignment": """
        creative_id STRING NOT NULL,
        creative_tag_id STRING NOT NULL,
        source_evidence_id STRING NOT NULL,
        observed_at TIMESTAMP NOT NULL
    """,
    "canonical_field_evidence": """
        entity_type STRING NOT NULL,
        entity_id STRING NOT NULL,
        field_name STRING NOT NULL,
        source_evidence_id STRING NOT NULL,
        asserted_value STRING,
        is_selected BOOLEAN NOT NULL,
        selection_reason STRING,
        observed_at TIMESTAMP NOT NULL
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
    "market": """
        market_id STRING NOT NULL,
        market_code STRING NOT NULL,
        market_name STRING NOT NULL,
        market_type STRING NOT NULL,
        parent_market_id STRING
    """,
    "campaign_market": """
        campaign_id STRING NOT NULL,
        market_id STRING NOT NULL
    """,
    "campaign_market_metric": """
        metric_id STRING NOT NULL,
        campaign_id STRING,
        product_id STRING,
        market_id STRING,
        metric_type STRING NOT NULL,
        value DOUBLE NOT NULL,
        unit STRING NOT NULL,
        measurement_start DATE,
        measurement_end DATE,
        measurement_period_precision STRING,
        observed_at TIMESTAMP NOT NULL,
        comparison_type STRING,
        comparison_start DATE,
        comparison_end DATE,
        comparison_period_precision STRING,
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
    # CREATE TABLE IF NOT EXISTS does not evolve tables created by an older job.
    additions = {
        "product_category": {
            "category_name": "STRING",
            "parent_category_id": "STRING",
            "taxonomy_name": "STRING",
            "taxonomy_version": "STRING",
        },
        "campaign_market_metric": {
            "market_id": "STRING",
            "measurement_period_precision": "STRING",
            "comparison_period_precision": "STRING",
        },
        "product_tag": {
            "tag_type": "STRING",
            "normalized_value": "STRING",
        },
        "product_tag_assignment": {
            "source_evidence_id": "STRING",
            "observed_at": "TIMESTAMP",
        },
    }
    for table, columns in additions.items():
        table_name = f"{catalog}.{namespace}.{table}"
        existing = set(spark.table(table_name).columns)
        missing = [f"{name} {kind}" for name, kind in columns.items() if name not in existing]
        if missing:
            spark.sql(f"ALTER TABLE {table_name} ADD COLUMNS ({', '.join(missing)})")
    campaign_table = f"{catalog}.{namespace}.advertising_campaign"
    relationship_field = next(
        field for field in spark.table(campaign_table).schema.fields
        if field.name == "relationship_type"
    )
    if not relationship_field.nullable:
        spark.sql(
            f"ALTER TABLE {campaign_table} ALTER COLUMN relationship_type DROP NOT NULL"
        )
    category_table = f"{catalog}.{namespace}.product_category"
    source_field = next(
        field for field in spark.table(category_table).schema.fields
        if field.name == "source_category_text"
    )
    if not source_field.nullable:
        spark.sql(
            f"ALTER TABLE {category_table} ALTER COLUMN source_category_text DROP NOT NULL"
        )


def _duplicates(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> bool:
    keys = [tuple(row.get(field) for field in fields) for row in rows]
    return len(keys) != len(set(keys))


def _validate_parent_hierarchy(
    rows: list[dict[str, Any]], id_field: str, parent_field: str, label: str
) -> None:
    parents = {row[id_field]: row.get(parent_field) for row in rows}
    for item_id, parent_id in parents.items():
        if parent_id is not None and parent_id not in parents:
            raise ValueError(f"Invalid {label} parent reference.")
        visited = {item_id}
        while parent_id is not None:
            if parent_id in visited:
                raise ValueError(f"Cyclic {label} parent reference.")
            visited.add(parent_id)
            parent_id = parents[parent_id]


def validate_advertising_silver_result(result: Any) -> None:
    """Validate references and constraints available inside one Silver batch."""
    collections = {
        "organization": (result.organizations, ("organization_id",)),
        "brand": (result.brands, ("brand_id",)),
        "product": (result.products, ("product_id",)),
        "product_category": (result.product_categories, ("category_id",)),
        "product_category_assignment": (
            result.product_category_assignments, ("product_id", "category_id")
        ),
        "product_tag": (result.product_tags, ("tag_id",)),
        "product_tag_assignment": (
            result.product_tag_assignments, ("product_id", "tag_id")
        ),
        "source_evidence": (result.source_evidence, ("source_evidence_id",)),
        "campaign": (result.campaigns, ("campaign_id",)),
        "campaign_brand": (
            result.campaign_brands, ("campaign_id", "brand_id")
        ),
        "advertisement_creative": (
            result.advertisement_creatives, ("creative_id",)
        ),
        "creative_tag": (result.creative_tags, ("creative_tag_id",)),
        "creative_tag_assignment": (
            result.creative_tag_assignments, ("creative_id", "creative_tag_id")
        ),
        "canonical_field_evidence": (
            result.canonical_field_evidence,
            ("entity_type", "entity_id", "field_name", "source_evidence_id"),
        ),
        "campaign_artist": (result.campaign_artists, ("campaign_artist_id",)),
        "campaign_product": (result.campaign_products, ("campaign_product_id",)),
        "market": (result.markets, ("market_id",)),
        "campaign_market": (result.campaign_markets, ("campaign_id", "market_id")),
        "market_metric": (result.market_metrics, ("metric_id",)),
    }
    for name, (rows, key) in collections.items():
        if _duplicates(rows, key):
            raise ValueError(f"Duplicate {name} key in advertising Silver result.")
    if _duplicates(result.markets, ("market_code",)):
        raise ValueError("Duplicate market_code in advertising Silver result.")
    identified_evidence = [
        row for row in result.source_evidence if row.get("source_record_id") is not None
    ]
    if _duplicates(identified_evidence, ("source_name", "source_record_id")):
        raise ValueError("Duplicate source identifier in advertising Silver result.")
    if _duplicates(
        result.advertisement_creatives, ("source_type", "source_creative_id")
    ):
        raise ValueError("Duplicate creative source identifier in advertising Silver result.")

    ids = {
        "organization": {row["organization_id"] for row in result.organizations},
        "brand": {row["brand_id"] for row in result.brands},
        "product": {row["product_id"] for row in result.products},
        "category": {row["category_id"] for row in result.product_categories},
        "tag": {row["tag_id"] for row in result.product_tags},
        "campaign": {row["campaign_id"] for row in result.campaigns},
        "market": {row["market_id"] for row in result.markets},
        "evidence": {row["source_evidence_id"] for row in result.source_evidence},
        "creative": {row["creative_id"] for row in result.advertisement_creatives},
        "creative_tag": {row["creative_tag_id"] for row in result.creative_tags},
    }
    references = (
        (result.brands, "organization_id", ids["organization"], True),
        (result.products, "brand_id", ids["brand"], False),
        (result.product_category_assignments, "product_id", ids["product"], False),
        (result.product_category_assignments, "category_id", ids["category"], False),
        (result.product_tag_assignments, "product_id", ids["product"], False),
        (result.product_tag_assignments, "tag_id", ids["tag"], False),
        (result.product_tag_assignments, "source_evidence_id", ids["evidence"], True),
        (result.campaign_brands, "campaign_id", ids["campaign"], False),
        (result.campaign_brands, "brand_id", ids["brand"], False),
        (result.advertisement_creatives, "campaign_id", ids["campaign"], True),
        (result.advertisement_creatives, "brand_id", ids["brand"], True),
        (result.advertisement_creatives, "product_id", ids["product"], True),
        (result.advertisement_creatives, "source_evidence_id", ids["evidence"], False),
        (result.creative_tag_assignments, "creative_id", ids["creative"], False),
        (result.creative_tag_assignments, "creative_tag_id", ids["creative_tag"], False),
        (result.creative_tag_assignments, "source_evidence_id", ids["evidence"], False),
        (result.canonical_field_evidence, "source_evidence_id", ids["evidence"], False),
        (result.campaign_artists, "campaign_id", ids["campaign"], False),
        (result.campaign_products, "campaign_id", ids["campaign"], False),
        (result.campaign_products, "product_id", ids["product"], False),
        (result.campaign_sources, "campaign_id", ids["campaign"], False),
        (result.campaign_markets, "campaign_id", ids["campaign"], False),
        (result.campaign_markets, "market_id", ids["market"], False),
        (result.market_metrics, "campaign_id", ids["campaign"], True),
        (result.market_metrics, "product_id", ids["product"], True),
        (result.market_metrics, "market_id", ids["market"], True),
    )
    for rows, field, valid, nullable in references:
        for row in rows:
            value = row.get(field)
            if value is None and nullable:
                continue
            if value not in valid:
                raise ValueError(f"Unknown {field} reference in advertising Silver result: {value!r}.")

    _validate_parent_hierarchy(
        result.product_categories,
        "category_id",
        "parent_category_id",
        "product category",
    )
    _validate_parent_hierarchy(
        result.markets, "market_id", "parent_market_id", "market"
    )
    for row in result.campaigns:
        start, end = row.get("campaign_start_date"), row.get("campaign_end_date")
        if start is not None and end is not None and date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("campaign_start_date must not be after campaign_end_date.")
    for row in result.campaign_artists:
        role = row.get("participation_role")
        if role is not None and role not in RELATIONSHIP_TYPES:
            raise ValueError(f"Unsupported participation_role: {role}.")
    for row in result.source_evidence:
        if row.get("authority_level") not in {
            "OFFICIAL", "STRUCTURED_PUBLIC_SOURCE", "PLATFORM_SOURCE", "DERIVED"
        }:
            raise ValueError("Unsupported source evidence authority_level.")
        if not isinstance(row.get("content_hash"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", row["content_hash"]
        ):
            raise ValueError("Invalid source evidence content_hash.")
    for row in result.advertisement_creatives:
        if row["first_observed_at"] > row["last_observed_at"]:
            raise ValueError("creative first_observed_at must not be after last_observed_at.")
        if row.get("active_from") and row.get("active_to") and row["active_from"] > row["active_to"]:
            raise ValueError("creative active_from must not be after active_to.")
    for row in result.market_metrics:
        for start_field, end_field in (
            ("measurement_start", "measurement_end"),
            ("comparison_start", "comparison_end"),
        ):
            start, end = row.get(start_field), row.get(end_field)
            if start is not None and end is not None and date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError(f"{start_field} must not be after {end_field}.")


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

    validate_advertising_silver_result(result)
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
                StructField("category_name", StringType(), False),
                StructField("parent_category_id", StringType(), True),
                StructField("taxonomy_name", StringType(), False),
                StructField("taxonomy_version", StringType(), False),
                StructField("source_category_text", StringType(), True),
            ]
        ),
        "product_category_assignment": StructType(
            [
                StructField("product_id", StringType(), False),
                StructField("category_id", StringType(), False),
            ]
        ),
        "product_tag": StructType(
            [
                StructField("tag_id", StringType(), False),
                StructField("tag_name", StringType(), False),
                StructField("tag_type", StringType(), True),
                StructField("normalized_value", StringType(), True),
            ]
        ),
        "product_tag_assignment": StructType(
            [
                StructField("product_id", StringType(), False),
                StructField("tag_id", StringType(), False),
                StructField("source_evidence_id", StringType(), True),
                StructField("observed_at", TimestampType(), True),
            ]
        ),
        "source_evidence": StructType(
            [
                StructField("source_evidence_id", StringType(), False),
                StructField("source_name", StringType(), False),
                StructField("source_type", StringType(), False),
                StructField("source_url", StringType(), True),
                StructField("source_record_id", StringType(), True),
                StructField("collected_at", TimestampType(), False),
                StructField("published_at", TimestampType(), True),
                StructField("content_hash", StringType(), False),
                StructField("authority_level", StringType(), False),
                StructField("raw_bronze_reference", StringType(), False),
                StructField("verification_status", StringType(), False),
            ]
        ),
        "advertising_campaign": StructType(
            [
                StructField("campaign_id", StringType(), False),
                StructField("campaign_name", StringType(), True),
                StructField("relationship_type", StringType(), True),
                StructField("announced_at", TimestampType(), True),
                StructField("campaign_start_date", DateType(), True),
                StructField("campaign_end_date", DateType(), True),
                StructField("status", StringType(), True),
            ]
        ),
        "campaign_brand": StructType(
            [
                StructField("campaign_id", StringType(), False),
                StructField("brand_id", StringType(), False),
            ]
        ),
        "advertisement_creative": StructType(
            [
                StructField("creative_id", StringType(), False),
                StructField("campaign_id", StringType(), True),
                StructField("brand_id", StringType(), True),
                StructField("product_id", StringType(), True),
                StructField("source_type", StringType(), False),
                StructField("source_creative_id", StringType(), False),
                StructField("creative_type", StringType(), False),
                StructField("title", StringType(), True),
                StructField("description", StringType(), True),
                StructField("media_url", StringType(), True),
                StructField("landing_url", StringType(), True),
                StructField("platform", StringType(), True),
                StructField("first_observed_at", TimestampType(), False),
                StructField("last_observed_at", TimestampType(), False),
                StructField("published_at", TimestampType(), True),
                StructField("active_from", TimestampType(), True),
                StructField("active_to", TimestampType(), True),
                StructField("source_evidence_id", StringType(), False),
            ]
        ),
        "creative_tag": StructType(
            [
                StructField("creative_tag_id", StringType(), False),
                StructField("tag_name", StringType(), False),
                StructField("tag_type", StringType(), False),
                StructField("normalized_value", StringType(), True),
                StructField("source_native_value", StringType(), True),
            ]
        ),
        "creative_tag_assignment": StructType(
            [
                StructField("creative_id", StringType(), False),
                StructField("creative_tag_id", StringType(), False),
                StructField("source_evidence_id", StringType(), False),
                StructField("observed_at", TimestampType(), False),
            ]
        ),
        "canonical_field_evidence": StructType(
            [
                StructField("entity_type", StringType(), False),
                StructField("entity_id", StringType(), False),
                StructField("field_name", StringType(), False),
                StructField("source_evidence_id", StringType(), False),
                StructField("asserted_value", StringType(), True),
                StructField("is_selected", BooleanType(), False),
                StructField("selection_reason", StringType(), True),
                StructField("observed_at", TimestampType(), False),
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
        "market": StructType(
            [
                StructField("market_id", StringType(), False),
                StructField("market_code", StringType(), False),
                StructField("market_name", StringType(), False),
                StructField("market_type", StringType(), False),
                StructField("parent_market_id", StringType(), True),
            ]
        ),
        "campaign_market": StructType(
            [
                StructField("campaign_id", StringType(), False),
                StructField("market_id", StringType(), False),
            ]
        ),
        "campaign_market_metric": StructType(
            [
                StructField("metric_id", StringType(), False),
                StructField("campaign_id", StringType(), True),
                StructField("product_id", StringType(), True),
                StructField("market_id", StringType(), True),
                StructField("metric_type", StringType(), False),
                StructField("value", DoubleType(), False),
                StructField("unit", StringType(), False),
                StructField("measurement_start", DateType(), True),
                StructField("measurement_end", DateType(), True),
                StructField("measurement_period_precision", StringType(), True),
                StructField("observed_at", TimestampType(), False),
                StructField("comparison_type", StringType(), True),
                StructField("comparison_start", DateType(), True),
                StructField("comparison_end", DateType(), True),
                StructField("comparison_period_precision", StringType(), True),
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
        "product_category_assignment": [
            dict(row) for row in result.product_category_assignments
        ],
        "product_tag": [dict(row) for row in result.product_tags],
        "product_tag_assignment": [dict(row) for row in result.product_tag_assignments],
        "source_evidence": [dict(row) for row in result.source_evidence],
        "advertising_campaign": [dict(row) for row in result.campaigns],
        "campaign_brand": [dict(row) for row in result.campaign_brands],
        "advertisement_creative": [dict(row) for row in result.advertisement_creatives],
        "creative_tag": [dict(row) for row in result.creative_tags],
        "creative_tag_assignment": [dict(row) for row in result.creative_tag_assignments],
        "canonical_field_evidence": [dict(row) for row in result.canonical_field_evidence],
        "campaign_artist": [dict(row) for row in result.campaign_artists],
        "campaign_product": [dict(row) for row in result.campaign_products],
        "campaign_source": [dict(row) for row in result.campaign_sources],
        "market": [dict(row) for row in result.markets],
        "campaign_market": [dict(row) for row in result.campaign_markets],
        "campaign_market_metric": [dict(row) for row in result.market_metrics],
    }
    for row in rows["advertising_campaign"]:
        if row["announced_at"] is not None:
            row["announced_at"] = _utc_datetime(row["announced_at"], "announced_at")
        for field in ("campaign_start_date", "campaign_end_date"):
            if row[field] is not None:
                row[field] = date.fromisoformat(row[field])
    for row in rows["product_tag"]:
        row.setdefault("tag_type", None)
        row.setdefault("normalized_value", None)
    for row in rows["product_tag_assignment"]:
        row.setdefault("source_evidence_id", None)
        observed_at = row.setdefault("observed_at", None)
        if observed_at is not None:
            row["observed_at"] = _utc_datetime(observed_at, "observed_at")
    for row in rows["source_evidence"]:
        row["collected_at"] = _utc_datetime(row["collected_at"], "collected_at")
        if row["published_at"] is not None:
            row["published_at"] = _utc_datetime(row["published_at"], "published_at")
    for table in ("advertisement_creative", "creative_tag_assignment", "canonical_field_evidence"):
        for row in rows[table]:
            for field in ("first_observed_at", "last_observed_at", "published_at", "active_from", "active_to", "observed_at"):
                if field in row and row[field] is not None:
                    row[field] = _utc_datetime(row[field], field)
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
        "product_category_assignment": (
            "target.product_id = source.product_id AND "
            "target.category_id = source.category_id"
        ),
        "product_tag": "target.tag_id = source.tag_id",
        "product_tag_assignment": (
            "target.product_id = source.product_id AND target.tag_id = source.tag_id"
        ),
        "source_evidence": "target.source_evidence_id = source.source_evidence_id",
        "advertising_campaign": "target.campaign_id = source.campaign_id",
        "campaign_brand": (
            "target.campaign_id = source.campaign_id AND "
            "target.brand_id = source.brand_id"
        ),
        "advertisement_creative": "target.creative_id = source.creative_id",
        "creative_tag": "target.creative_tag_id = source.creative_tag_id",
        "creative_tag_assignment": (
            "target.creative_id = source.creative_id AND "
            "target.creative_tag_id = source.creative_tag_id"
        ),
        "canonical_field_evidence": (
            "target.entity_type = source.entity_type AND "
            "target.entity_id = source.entity_id AND "
            "target.field_name = source.field_name AND "
            "target.source_evidence_id = source.source_evidence_id"
        ),
        "campaign_artist": "target.campaign_artist_id = source.campaign_artist_id",
        "campaign_product": "target.campaign_product_id = source.campaign_product_id",
        "campaign_source": (
            "target.campaign_id = source.campaign_id AND "
            "target.bronze_object_reference = source.bronze_object_reference"
        ),
        "market": "target.market_id = source.market_id",
        "campaign_market": (
            "target.campaign_id = source.campaign_id AND target.market_id = source.market_id"
        ),
        "campaign_market_metric": "target.metric_id = source.metric_id",
    }
    for table in rows:
        _merge_advertising(spark, table, rows[table], schemas[table], conditions[table])
