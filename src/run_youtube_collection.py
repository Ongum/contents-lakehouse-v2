"""Collect RESCENE YouTube API responses into the configured Bronze store."""

from uuid import uuid4

if __package__:
    from .bronze_storage import BronzeStorage
    from .pipeline_logging import PipelineRunLogger, utc_now
    from .storage_factory import bronze_storage_from_environment
    from .youtube_connectivity import BronzeCapture, collect_seed_videos, get_api_key
else:
    from bronze_storage import BronzeStorage
    from pipeline_logging import PipelineRunLogger, utc_now
    from storage_factory import bronze_storage_from_environment
    from youtube_connectivity import BronzeCapture, collect_seed_videos, get_api_key


def main() -> int:
    run_id = str(uuid4())
    observed_at = utc_now()
    logger = PipelineRunLogger("youtube_collection", run_id, observed_at)
    logger.pipeline_started()
    try:
        logger.stage_started("bronze_collection")
        storage = bronze_storage_from_environment(BronzeStorage)
        storage.ensure_bucket()
        capture = BronzeCapture(
            run_id=run_id,
            observed_at=observed_at,
            record_sink=storage.write_record,
            failure_sink=storage.write_failure,
        )
        videos = collect_seed_videos(get_api_key(), capture)
        capture.raise_for_failures()
        logger.stage_succeeded(
            "bronze_collection",
            bronze_objects=len(capture.records),
            videos=len(videos),
        )
        logger.pipeline_succeeded(bronze_objects=len(capture.records), videos=len(videos))
        return 0
    except Exception as error:
        logger.pipeline_failed(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
