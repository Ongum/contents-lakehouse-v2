"""Production entrypoint for the scheduled RESCENE Narangd pipeline."""

from uuid import uuid4

if __package__:
    from .advertising_bronze_storage import AdvertisingBronzeStorage
    from .advertising_collection import CollectionStatus, collect_source
    from .advertising_silver import transform_advertising_bronze
    from .advertising_silver_iceberg import persist_advertising_silver_result
    from .advertising_sources import NARANGD_SOURCE, narangd_identity_content
    from .http_document_adapter import HttpDocumentAdapter
    from .pipeline_logging import PipelineRunLogger, utc_now
    from .silver_iceberg import build_spark_session
else:
    from advertising_bronze_storage import AdvertisingBronzeStorage
    from advertising_collection import CollectionStatus, collect_source
    from advertising_silver import transform_advertising_bronze
    from advertising_silver_iceberg import persist_advertising_silver_result
    from advertising_sources import NARANGD_SOURCE, narangd_identity_content
    from http_document_adapter import HttpDocumentAdapter
    from pipeline_logging import PipelineRunLogger, utc_now
    from silver_iceberg import build_spark_session


def main() -> int:
    run_id = str(uuid4())
    started_at = utc_now()
    logger = PipelineRunLogger("advertising", run_id, started_at)
    logger.pipeline_started()
    spark = None
    try:
        logger.stage_started("bronze_collection")
        storage = AdvertisingBronzeStorage.from_environment()
        storage.ensure_bucket()
        adapter = HttpDocumentAdapter(
            identity_canonicalizer=narangd_identity_content
        )
        collected = collect_source(
            NARANGD_SOURCE,
            adapter,
            storage,
            run_id=run_id,
            retrieved_at=started_at,
        )
        if collected.status not in {
            CollectionStatus.SUCCESS,
            CollectionStatus.UNCHANGED,
        }:
            raise RuntimeError(
                f"Advertising collection failed with {collected.status.value}: "
                f"{collected.error_message}"
            )
        logger.stage_succeeded(
            "bronze_collection",
            collection_status=collected.status.value,
            bronze_objects_created=int(collected.content_created),
        )

        logger.stage_started("silver_transformation")
        envelope = collected.record
        result = transform_advertising_bronze(collected.object_key, envelope)
        if result.invalid_records:
            raise RuntimeError(result.invalid_records[0]["error_message"])
        logger.stage_succeeded(
            "silver_transformation",
            organizations=len(result.organizations),
            campaigns=len(result.campaigns),
            metrics=len(result.market_metrics),
        )

        logger.stage_started("silver_iceberg")
        spark = build_spark_session()
        persist_advertising_silver_result(spark, result)
        logger.stage_succeeded("silver_iceberg")
        logger.pipeline_succeeded(
            collection_status=collected.status.value,
            campaigns=len(result.campaigns),
            metrics=len(result.market_metrics),
        )
        return 0
    except Exception as error:
        logger.pipeline_failed(error)
        return 1
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    raise SystemExit(main())
