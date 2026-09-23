"""Minimal structured logging for one-shot local pipeline entrypoints."""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


SECRET_ENV_NAMES = (
    "YOUTUBE_API_KEY",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_error_message(error: BaseException) -> str:
    message = str(error)
    for name in SECRET_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            message = message.replace(value, "[REDACTED]")
    return message


class PipelineRunLogger:
    def __init__(self, pipeline: str, run_id: str, started_at: str) -> None:
        self.pipeline = pipeline
        self.run_id = run_id
        self.started_at = started_at
        self.stage = "pipeline"

    def _write(self, status: str, stage: str, **values: Any) -> None:
        event = {
            "pipeline": self.pipeline,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": utc_now() if status in {"SUCCEEDED", "FAILED"} else None,
            "status": status,
            "stage": stage,
            **values,
        }
        stream = sys.stderr if status == "FAILED" else sys.stdout
        print(json.dumps(event, ensure_ascii=False, sort_keys=True), file=stream)

    def pipeline_started(self) -> None:
        self._write("STARTED", "pipeline")

    def stage_started(self, stage: str) -> None:
        self.stage = stage
        self._write("STARTED", stage)

    def stage_succeeded(self, stage: str, **counts: Any) -> None:
        self._write("SUCCEEDED", stage, **counts)

    def pipeline_succeeded(self, **counts: Any) -> None:
        self._write("SUCCEEDED", "pipeline", **counts)

    def pipeline_failed(self, error: BaseException) -> None:
        self._write(
            "FAILED",
            self.stage,
            error_type=type(error).__name__,
            error_message=safe_error_message(error),
        )
