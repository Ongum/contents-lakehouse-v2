"""Publish the immutable GCS snapshot; dry-run unless --apply is supplied."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bigquery_analysis import (  # noqa: E402
    DEFAULT_MANIFEST,
    build_snapshot_plan,
)
from src.bigquery_snapshot import publish_snapshot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID", ""))
    parser.add_argument("--bucket", default=os.environ.get("GCS_BUCKET", ""))
    parser.add_argument("--snapshot-id", default=os.environ.get("BIGQUERY_SNAPSHOT_ID"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform create-only GCS writes. Without this flag, print the plan only.",
    )
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

    from google.cloud import storage

    client = storage.Client(project=args.project)
    actions = publish_snapshot(plan, args.bucket, client, apply=args.apply)
    print(json.dumps({"apply": args.apply, "snapshot_id": snapshot_id, "actions": actions}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
