"""Production entrypoint for the scheduled English RESCENE MediaWiki pipeline."""

from uuid import uuid4

if __package__:
    from .mediawiki_bronze import MediaWikiBronzeStorage, ingest_latest_revision
    from .mediawiki_silver import transform_mediawiki_bronze
    from .mediawiki_silver_iceberg import persist_mediawiki_silver_result
    from .pipeline_logging import PipelineRunLogger, utc_now
    from .silver_iceberg import build_spark_session
else:
    from mediawiki_bronze import MediaWikiBronzeStorage, ingest_latest_revision
    from mediawiki_silver import transform_mediawiki_bronze
    from mediawiki_silver_iceberg import persist_mediawiki_silver_result
    from pipeline_logging import PipelineRunLogger, utc_now
    from silver_iceberg import build_spark_session


def main() -> int:
    run_id = str(uuid4())
    started_at = utc_now()
    logger = PipelineRunLogger("mediawiki", run_id, started_at)
    logger.pipeline_started()
    spark = None
    try:
        logger.stage_started("bronze_collection")
        storage = MediaWikiBronzeStorage.from_environment()
        storage.ensure_bucket()
        object_name, created, record = ingest_latest_revision(storage)
        logger.stage_succeeded(
            "bronze_collection",
            bronze_objects_created=int(created),
            revision_id=record["revision_id"],
        )

        logger.stage_started("silver_transformation")
        result = transform_mediawiki_bronze(object_name, record)
        if result.invalid_records:
            raise RuntimeError(result.invalid_records[0]["error_message"])
        logger.stage_succeeded(
            "silver_transformation",
            artists=len(result.artists),
            relationships=len(result.artist_relationships),
            events=len(result.artist_events),
        )

        logger.stage_started("silver_iceberg")
        spark = build_spark_session()
        persist_mediawiki_silver_result(spark, result)
        logger.stage_succeeded("silver_iceberg")
        logger.pipeline_succeeded(
            bronze_objects_created=int(created),
            artists=len(result.artists),
            events=len(result.artist_events),
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
