"""Verify persisted Narangd Bronze to advertising Silver Iceberg."""

import os

from advertising_bronze_storage import AdvertisingBronzeStorage
from advertising_silver import AdvertisingTransformError, transform_latest_from_minio
from advertising_silver_iceberg import persist_advertising_silver_result
from bronze_storage import BronzeStorageError
from mvp_config import RESCENE_ARTIST_ID
from silver_iceberg import SilverPersistenceError, build_spark_session


def _ids(rows, field):
    return [row[field] for row in rows]


def main() -> int:
    storage = AdvertisingBronzeStorage.from_environment()
    storage.ensure_bucket()
    result = transform_latest_from_minio(storage)
    if result.invalid_records:
        raise AdvertisingTransformError(result.invalid_records[0]["error_message"])

    spark = build_spark_session()
    try:
        persist_advertising_silver_result(spark, result)
        persist_advertising_silver_result(spark, result)
        catalog = os.environ.get("ICEBERG_CATALOG", "lakehouse")
        namespace = os.environ.get("SILVER_NAMESPACE", "silver")
        prefix = f"{catalog}.{namespace}"
        expected = {
            "advertiser_organization": (
                "organization_id",
                _ids(result.organizations, "organization_id"),
            ),
            "brand": ("brand_id", _ids(result.brands, "brand_id")),
            "product": ("product_id", _ids(result.products, "product_id")),
            "advertising_campaign": (
                "campaign_id",
                _ids(result.campaigns, "campaign_id"),
            ),
            "campaign_artist": (
                "campaign_artist_id",
                _ids(result.campaign_artists, "campaign_artist_id"),
            ),
            "campaign_product": (
                "campaign_product_id",
                _ids(result.campaign_products, "campaign_product_id"),
            ),
            "campaign_market_metric": (
                "metric_id",
                _ids(result.market_metrics, "metric_id"),
            ),
        }
        for table, (key, values) in expected.items():
            if not values:
                continue
            frame = spark.table(f"{prefix}.{table}")
            count = frame.filter(frame[key].isin(values)).count()
            if count != len(values):
                raise SilverPersistenceError(
                    f"Advertising Silver verification failed for {table}: {count}."
                )
        campaign_id = result.campaigns[0]["campaign_id"]
        source = spark.table(f"{prefix}.campaign_source")
        source_count = source.filter(
            (source.campaign_id == campaign_id)
            & (
                source.bronze_object_reference
                == result.campaign_sources[0]["bronze_object_reference"]
            )
        ).count()
        artist = spark.table(f"{prefix}.campaign_artist")
        artist_count = artist.filter(
            (artist.campaign_id == campaign_id)
            & (artist.artist_id == RESCENE_ARTIST_ID)
        ).count()
        if source_count != 1 or artist_count != 1:
            raise SilverPersistenceError(
                "Advertising Silver source or artist idempotency verification failed."
            )
    finally:
        spark.stop()

    print("Advertising Bronze-to-Silver verification succeeded.")
    print("Organizations: " + ", ".join(x["organization_name"] for x in result.organizations))
    print("Brands: " + ", ".join(x["brand_name"] for x in result.brands))
    print("Products: " + (", ".join(x["product_name"] for x in result.products) or "none"))
    print(f"Campaign: {result.campaigns[0]}")
    print(f"Campaign artist: {result.campaign_artists[0]}")
    print(f"Campaign products: {len(result.campaign_products)}")
    print("Market metrics:")
    for metric in result.market_metrics:
        print(
            f"- {metric['metric_type']}: {metric['value']} {metric['unit']} "
            f"(company_reported={metric['is_company_reported']})"
        )
    print(
        "Bronze reference: "
        + result.campaign_sources[0]["bronze_object_reference"]
    )
    print("Repeated write verified without duplicate canonical rows.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        AdvertisingTransformError,
        BronzeStorageError,
        SilverPersistenceError,
    ) as error:
        raise SystemExit(f"Error: {error}") from error
