"""Production entrypoint for the scheduled RESCENE YouTube pipeline."""

from uuid import uuid4

if __package__:
    from .pipeline_logging import PipelineRunLogger, utc_now
    from .run_pipeline import main as run_existing_youtube_pipeline
else:
    from pipeline_logging import PipelineRunLogger, utc_now
    from run_pipeline import main as run_existing_youtube_pipeline


def main() -> int:
    run_id = str(uuid4())
    started_at = utc_now()
    logger = PipelineRunLogger("youtube", run_id, started_at)
    logger.pipeline_started()
    try:
        logger.stage_started("youtube_bronze_to_gold")
        result = run_existing_youtube_pipeline(
            run_id=run_id, observed_at=started_at
        )
        if result != 0:
            raise RuntimeError(f"Existing YouTube pipeline returned {result}.")
        logger.stage_succeeded("youtube_bronze_to_gold")
        logger.pipeline_succeeded()
        return 0
    except Exception as error:
        logger.pipeline_failed(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
