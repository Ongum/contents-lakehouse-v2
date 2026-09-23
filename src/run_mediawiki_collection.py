"""Collect the latest English Rescene revision into the configured Bronze store."""

from uuid import uuid4

if __package__:
    from .mediawiki_bronze import MediaWikiBronzeStorage, ingest_latest_revision
    from .pipeline_logging import PipelineRunLogger, utc_now
    from .storage_factory import bronze_storage_from_environment
else:
    from mediawiki_bronze import MediaWikiBronzeStorage, ingest_latest_revision
    from pipeline_logging import PipelineRunLogger, utc_now
    from storage_factory import bronze_storage_from_environment


def main() -> int:
    run_id = str(uuid4())
    started_at = utc_now()
    logger = PipelineRunLogger("mediawiki_collection", run_id, started_at)
    logger.pipeline_started()
    try:
        logger.stage_started("bronze_collection")
        storage = bronze_storage_from_environment(MediaWikiBronzeStorage)
        storage.ensure_bucket()
        object_name, created, record = ingest_latest_revision(storage)
        logger.stage_succeeded(
            "bronze_collection",
            bronze_objects_created=int(created),
            revision_id=record["revision_id"],
            object_name=object_name,
        )
        logger.pipeline_succeeded(bronze_objects_created=int(created))
        return 0
    except Exception as error:
        logger.pipeline_failed(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
