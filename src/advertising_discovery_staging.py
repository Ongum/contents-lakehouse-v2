"""Persist provisional KR advertising candidates outside canonical Silver."""

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

if __package__:
    from .advertising_discovery import deduplicate_candidates
else:
    from advertising_discovery import deduplicate_candidates


TABLE_NAME = "advertising_campaign_candidate"
TABLE_DEFINITION = """
    candidate_id STRING NOT NULL,
    discovered_for_artist_id STRING,
    discovery_signal STRING,
    discovered_at TIMESTAMP NOT NULL,
    discovery_source STRING NOT NULL,
    source_url STRING NOT NULL,
    advertiser_brand_text STRING NOT NULL,
    product_text STRING,
    campaign_text STRING,
    artist_model_text STRING,
    publication_date DATE,
    market_code STRING NOT NULL,
    evidence_status STRING NOT NULL,
    official_source_url STRING,
    rejection_reason STRING
"""


@dataclass(frozen=True)
class CandidatePersistenceResult:
    inserted: int
    already_existing: int


def _identifier(name: str, value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid {name}: {value!r}.")
    return value


def _table_name() -> str:
    catalog = _identifier(
        "ICEBERG_CATALOG", os.environ.get("ICEBERG_CATALOG", "lakehouse")
    )
    namespace = _identifier(
        "ADVERTISING_DISCOVERY_NAMESPACE",
        os.environ.get("ADVERTISING_DISCOVERY_NAMESPACE", "staging"),
    )
    if namespace == os.environ.get("SILVER_NAMESPACE", "silver"):
        raise ValueError("Advertising discovery namespace must be separate from Silver.")
    return f"{catalog}.{namespace}.{TABLE_NAME}"


def create_candidate_table(spark: Any) -> str:
    table_name = _table_name()
    namespace = table_name.rsplit(".", 1)[0]
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {namespace}")
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {table_name} ({TABLE_DEFINITION}) "
        "USING iceberg TBLPROPERTIES ('format-version' = '2')"
    )
    existing = set(spark.table(table_name).columns)
    additions = []
    if "discovered_for_artist_id" not in existing:
        additions.append("discovered_for_artist_id STRING")
    if "discovery_signal" not in existing:
        additions.append("discovery_signal STRING")
    if additions:
        spark.sql(f"ALTER TABLE {table_name} ADD COLUMNS ({', '.join(additions)})")
    return table_name


def persist_discovered_candidates(
    spark: Any, candidates: list[dict[str, Any]]
) -> CandidatePersistenceResult:
    """Insert new identities only; repeat discoveries cannot overwrite staging rows."""
    candidates = deduplicate_candidates(candidates)
    if not candidates:
        return CandidatePersistenceResult(0, 0)
    from pyspark.sql.types import DateType, StringType, StructField, StructType, TimestampType

    table_name = create_candidate_table(spark)
    candidate_ids = [candidate["candidate_id"] for candidate in candidates]
    table = spark.table(table_name)
    existing_ids = {
        row["candidate_id"]
        for row in table.filter(table.candidate_id.isin(candidate_ids))
        .select("candidate_id")
        .collect()
    }
    rows = [dict(candidate) for candidate in candidates]
    for row in rows:
        row["discovered_at"] = datetime.fromisoformat(
            row["discovered_at"].replace("Z", "+00:00")
        )
        if row["publication_date"] is not None:
            row["publication_date"] = date.fromisoformat(row["publication_date"])
    schema = StructType(
        [
            StructField("candidate_id", StringType(), False),
            StructField("discovered_for_artist_id", StringType(), True),
            StructField("discovery_signal", StringType(), True),
            StructField("discovered_at", TimestampType(), False),
            StructField("discovery_source", StringType(), False),
            StructField("source_url", StringType(), False),
            StructField("advertiser_brand_text", StringType(), False),
            StructField("product_text", StringType(), True),
            StructField("campaign_text", StringType(), True),
            StructField("artist_model_text", StringType(), True),
            StructField("publication_date", DateType(), True),
            StructField("market_code", StringType(), False),
            StructField("evidence_status", StringType(), False),
            StructField("official_source_url", StringType(), True),
            StructField("rejection_reason", StringType(), True),
        ]
    )
    view = "incoming_advertising_campaign_candidate"
    spark.createDataFrame(rows, schema=schema).createOrReplaceTempView(view)
    columns = [field.name for field in schema.fields]
    spark.sql(
        f"MERGE INTO {table_name} target USING {view} source "
        "ON target.candidate_id = source.candidate_id "
        f"WHEN NOT MATCHED THEN INSERT ({', '.join(columns)}) "
        f"VALUES ({', '.join(f'source.{column}' for column in columns)})"
    )
    spark.catalog.dropTempView(view)
    return CandidatePersistenceResult(
        inserted=len(candidate_ids) - len(existing_ids),
        already_existing=len(existing_ids),
    )
