"""Build an immutable GCS snapshot plan and BigQuery external-table DDL.

This module does not mutate GCS or BigQuery.  It turns the checked-in EDA
manifest into a reviewable publication plan and SQL that can be applied only
after the corresponding snapshot objects have been published.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = Path("data/eda/youtube_september_2026/manifest.json")
SNAPSHOT_PREFIX = "silver/analysis_snapshots"
LIVE_ARTIST_ACTIVITY_OBJECT = "silver/artist_activity/artist_activity.parquet"
ARTIST_ACTIVITY_COLUMNS = (
    "source_url",
    "source_id",
    "notice_title",
    "notice_published_at",
    "group_name",
    "artist_name",
    "activity_type",
    "activity_name",
    "event_start_at",
    "event_end_at",
    "venue",
    "city",
    "raw_text",
    "collected_at",
    "content_hash",
    "source_updated_at",
    "bronze_object",
)

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
_DATASET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
_SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")


class BigQueryAnalysisError(ValueError):
    """Raised when a snapshot or BigQuery projection is unsafe or incomplete."""


@dataclass(frozen=True)
class SnapshotObject:
    table: str
    source_kind: str
    source: str
    destination: str
    row_count: int | None
    columns: tuple[str, ...]


def _require_match(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise BigQueryAnalysisError(f"Invalid {label}: {value!r}.")
    return value


def default_snapshot_id(exported_at_utc: str) -> str:
    value = datetime.fromisoformat(exported_at_utc.replace("Z", "+00:00"))
    return value.strftime("%Y%m%dT%H%M%SZ")


def load_eda_manifest(repo_root: Path, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    path = (repo_root / manifest_path).resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as error:
        raise BigQueryAnalysisError("EDA manifest must remain inside the repository.") from error
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BigQueryAnalysisError(f"Unable to read EDA manifest {path}: {error}") from error
    if manifest.get("contract_version") != 1 or not isinstance(manifest.get("tables"), list):
        raise BigQueryAnalysisError("Unsupported or incomplete EDA manifest contract.")
    manifest["_path"] = str(path)
    return manifest


def _parquet_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix == ".parquet":
        return [path]
    if path.is_dir():
        return sorted(
            candidate
            for candidate in path.glob("*.parquet")
            if candidate.is_file() and not candidate.name.startswith(".")
        )
    return []


def build_snapshot_plan(
    repo_root: Path,
    bucket: str,
    snapshot_id: str,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> list[SnapshotObject]:
    """Return every immutable object needed by the 19-table analysis snapshot."""
    _require_match(bucket, _BUCKET_RE, "GCS bucket")
    _require_match(snapshot_id, _SNAPSHOT_RE, "snapshot ID")
    manifest = load_eda_manifest(repo_root, manifest_path)
    manifest_file = Path(manifest["_path"])
    plan: list[SnapshotObject] = []
    table_names: set[str] = set()
    for entry in manifest["tables"]:
        source_table = str(entry.get("source_table", ""))
        table = source_table.rsplit(".", 1)[-1]
        _require_match(table, _TABLE_RE, "table name")
        if table in table_names:
            raise BigQueryAnalysisError(f"Duplicate manifest table: {table}.")
        table_names.add(table)
        source_path = (manifest_file.parent / str(entry.get("output", ""))).resolve()
        try:
            source_path.relative_to(repo_root.resolve())
        except ValueError as error:
            raise BigQueryAnalysisError(f"Source path escapes repository: {source_path}") from error
        files = _parquet_files(source_path)
        if not files:
            raise BigQueryAnalysisError(f"No Parquet data found for {table}: {source_path}")
        columns = tuple(str(column) for column in entry.get("columns", []))
        if not columns:
            raise BigQueryAnalysisError(f"No columns recorded for {table}.")
        for index, source_file in enumerate(files):
            destination_name = source_file.name
            if source_path.is_file():
                destination_name = f"part-{index:05d}.parquet"
            destination = (
                f"{SNAPSHOT_PREFIX}/snapshot_id={snapshot_id}/"
                f"{table}/{destination_name}"
            )
            plan.append(
                SnapshotObject(
                    table=table,
                    source_kind="local",
                    source=str(source_file),
                    destination=destination,
                    row_count=int(entry["row_count"]),
                    columns=columns,
                )
            )

    # Mnet Plus is cloud-managed and newer than the local 12-row seed.  Copy the
    # live object server-side into the same immutable snapshot as the EDA tables.
    plan.append(
        SnapshotObject(
            table="artist_activity",
            source_kind="gcs",
            source=f"gs://{bucket}/{LIVE_ARTIST_ACTIVITY_OBJECT}",
            destination=(
                f"{SNAPSHOT_PREFIX}/snapshot_id={snapshot_id}/"
                "artist_activity/part-00000.parquet"
            ),
            row_count=None,
            columns=ARTIST_ACTIVITY_COLUMNS,
        )
    )
    return plan


def _qualified(project: str, dataset: str, table: str) -> str:
    return f"`{project}.{dataset}.{table}`"


def _qualified_dataset(project: str, dataset: str) -> str:
    return f"`{project}.{dataset}`"


def _youtube_video_projection(project: str, dataset: str, columns: tuple[str, ...]) -> str:
    expressions = []
    for column in columns:
        if column == "tags":
            expressions.append(
                "CASE WHEN tags IS NULL THEN NULL "
                "ELSE ARRAY(SELECT item.element FROM UNNEST(tags.list) AS item) "
                "END AS tags"
            )
        else:
            expressions.append(column)
    source = _qualified(project, dataset, "youtube_video_external")
    return "SELECT\n  " + ",\n  ".join(expressions) + f"\nFROM {source}"


def render_bigquery_ddl(
    plan: list[SnapshotObject],
    project: str,
    dataset: str,
    bucket: str,
    snapshot_id: str,
    location: str = "asia-northeast1",
) -> str:
    """Render idempotent external tables plus stable analyst-facing views."""
    _require_match(project, _PROJECT_RE, "GCP project")
    _require_match(dataset, _DATASET_RE, "BigQuery dataset")
    _require_match(bucket, _BUCKET_RE, "GCS bucket")
    _require_match(snapshot_id, _SNAPSHOT_RE, "snapshot ID")
    if not re.fullmatch(r"^[A-Za-z0-9-]+$", location):
        raise BigQueryAnalysisError(f"Invalid BigQuery location: {location!r}.")

    by_table: dict[str, SnapshotObject] = {}
    for item in plan:
        previous = by_table.get(item.table)
        if previous is not None and previous.columns != item.columns:
            raise BigQueryAnalysisError(f"Inconsistent columns for {item.table}.")
        by_table[item.table] = item
    if len(by_table) != 19:
        raise BigQueryAnalysisError(
            f"Expected 19 analyst tables, found {len(by_table)}: {sorted(by_table)}"
        )

    statements = [
        "-- Generated by scripts/prepare_bigquery_analysis.py; do not edit by hand.",
        f"CREATE SCHEMA IF NOT EXISTS {_qualified_dataset(project, dataset)}",
        f"OPTIONS(location='{location}');",
    ]
    for table in sorted(by_table):
        external = f"{table}_external"
        uri = (
            f"gs://{bucket}/{SNAPSHOT_PREFIX}/snapshot_id={snapshot_id}/"
            f"{table}/*.parquet"
        )
        statements.extend(
            [
                "",
                f"CREATE OR REPLACE EXTERNAL TABLE {_qualified(project, dataset, external)}",
                "OPTIONS(",
                "  format='PARQUET',",
                f"  uris=['{uri}']",
                ");",
                "",
                f"CREATE OR REPLACE VIEW {_qualified(project, dataset, table)} AS",
            ]
        )
        spec = by_table[table]
        if table == "youtube_video":
            statements.append(_youtube_video_projection(project, dataset, spec.columns) + ";")
        else:
            columns = ",\n  ".join(spec.columns)
            statements.append(
                f"SELECT\n  {columns}\nFROM {_qualified(project, dataset, external)};"
            )
    return "\n".join(statements) + "\n"


def plan_as_json(plan: list[SnapshotObject]) -> str:
    return json.dumps(
        [
            {
                "table": item.table,
                "source_kind": item.source_kind,
                "source": item.source,
                "destination": item.destination,
                "row_count": item.row_count,
                "columns": list(item.columns),
            }
            for item in plan
        ],
        ensure_ascii=False,
        indent=2,
    ) + "\n"
