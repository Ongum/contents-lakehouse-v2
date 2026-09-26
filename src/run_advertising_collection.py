"""Collect the configured RESCENE advertising source into Bronze."""

from uuid import uuid4

if __package__:
    from .advertising_bronze_storage import AdvertisingBronzeStorage
    from .advertising_collection import CollectionStatus, collect_source
    from .advertising_sources import NARANGD_SOURCE, narangd_identity_content
    from .http_document_adapter import HttpDocumentAdapter
    from .pipeline_logging import PipelineRunLogger, utc_now
    from .storage_factory import bronze_storage_from_environment
else:
    from advertising_bronze_storage import AdvertisingBronzeStorage
    from advertising_collection import CollectionStatus, collect_source
    from advertising_sources import NARANGD_SOURCE, narangd_identity_content
    from http_document_adapter import HttpDocumentAdapter
    from pipeline_logging import PipelineRunLogger, utc_now
    from storage_factory import bronze_storage_from_environment


def main() -> int:
    run_id = str(uuid4())
    started_at = utc_now()
    logger = PipelineRunLogger("advertising_collection", run_id, started_at)
    logger.pipeline_started()
    try:
        logger.stage_started("bronze_collection")
        storage = bronze_storage_from_environment(AdvertisingBronzeStorage)
        storage.ensure_bucket()
        result = collect_source(
            NARANGD_SOURCE,
            HttpDocumentAdapter(identity_canonicalizer=narangd_identity_content),
            storage,
            run_id=run_id,
            retrieved_at=started_at,
        )
        if result.status not in {CollectionStatus.SUCCESS, CollectionStatus.UNCHANGED}:
            raise RuntimeError(
                f"Advertising collection failed with {result.status.value}: "
                f"{result.error_message}"
            )
        logger.stage_succeeded(
            "bronze_collection",
            collection_status=result.status.value,
            bronze_objects_created=int(result.content_created),
            observation_reference=result.observation_key,
            object_name=result.object_key,
        )
        logger.pipeline_succeeded(collection_status=result.status.value)
        return 0
    except Exception as error:
        logger.pipeline_failed(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
