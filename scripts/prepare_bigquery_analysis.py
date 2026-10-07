"""Render, but never apply, the BigQuery analysis snapshot plan and DDL."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bigquery_analysis import (  # noqa: E402
    DEFAULT_MANIFEST,
    build_snapshot_plan,
    plan_as_json,
    render_bigquery_ddl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare an immutable 19-table GCS snapshot and BigQuery DDL."
    )
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID", ""))
    parser.add_argument("--dataset", default=os.environ.get("BIGQUERY_DATASET", "contents_lakehouse"))
    parser.add_argument("--bucket", default=os.environ.get("GCS_BUCKET", ""))
    parser.add_argument("--location", default=os.environ.get("BIGQUERY_LOCATION", "asia-northeast1"))
    parser.add_argument("--snapshot-id", default=os.environ.get("BIGQUERY_SNAPSHOT_ID"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--format", choices=("sql", "plan"), default="sql")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.project or not args.bucket:
        raise SystemExit("--project/GCP_PROJECT_ID and --bucket/GCS_BUCKET are required.")
    repo_root = Path(__file__).resolve().parents[1]
    if not args.snapshot_id:
        raise SystemExit("--snapshot-id/BIGQUERY_SNAPSHOT_ID is required and must identify this publication.")
    snapshot_id = args.snapshot_id
    plan = build_snapshot_plan(repo_root, args.bucket, snapshot_id, args.manifest)
    content = (
        plan_as_json(plan)
        if args.format == "plan"
        else render_bigquery_ddl(
            plan,
            args.project,
            args.dataset,
            args.bucket,
            snapshot_id,
            args.location,
        )
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"Wrote {args.format} to {args.output}")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
