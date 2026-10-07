"""Publish a reviewed BigQuery analysis snapshot to GCS.

Publication is create-only. Re-running an identical plan skips matching objects;
an object with different content at the same immutable destination is an error.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from .bigquery_analysis import BigQueryAnalysisError, SnapshotObject, plan_as_json


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 -- GCS integrity comparison, not security.
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode("ascii")


def _md5_bytes(content: bytes) -> str:
    digest = hashlib.md5(content).digest()  # noqa: S324 -- GCS integrity comparison.
    return base64.b64encode(digest).decode("ascii")


def _matching_blob(blob: Any, expected_md5: str | None, expected_crc32c: str | None) -> bool:
    blob.reload()
    if expected_md5 and blob.md5_hash:
        return blob.md5_hash == expected_md5
    if expected_crc32c and blob.crc32c:
        return blob.crc32c == expected_crc32c
    return False


def publish_snapshot(
    plan: list[SnapshotObject],
    bucket_name: str,
    client: Any,
    apply: bool = False,
) -> list[dict[str, str]]:
    """Dry-run or create the immutable objects represented by ``plan``."""
    bucket = client.bucket(bucket_name)
    actions: list[dict[str, str]] = []
    for item in plan:
        destination = bucket.blob(item.destination)
        if item.source_kind == "local":
            source_path = Path(item.source)
            expected_md5 = _md5_file(source_path)
            if destination.exists(client=client):
                if not _matching_blob(destination, expected_md5, None):
                    raise BigQueryAnalysisError(
                        f"Immutable destination differs from local source: {item.destination}"
                    )
                actions.append({"table": item.table, "action": "skip", "object": item.destination})
            elif apply:
                destination.upload_from_filename(
                    str(source_path),
                    content_type="application/vnd.apache.parquet",
                    if_generation_match=0,
                )
                actions.append({"table": item.table, "action": "upload", "object": item.destination})
            else:
                actions.append({"table": item.table, "action": "would_upload", "object": item.destination})
            continue

        expected_prefix = f"gs://{bucket_name}/"
        if item.source_kind != "gcs" or not item.source.startswith(expected_prefix):
            raise BigQueryAnalysisError(f"Unsupported snapshot source: {item.source}")
        source_name = item.source[len(expected_prefix) :]
        source = bucket.blob(source_name)
        if not source.exists(client=client):
            raise BigQueryAnalysisError(f"Missing live GCS source: {item.source}")
        source.reload()
        if destination.exists(client=client):
            if not _matching_blob(destination, source.md5_hash, source.crc32c):
                raise BigQueryAnalysisError(
                    f"Immutable destination differs from GCS source: {item.destination}"
                )
            actions.append({"table": item.table, "action": "skip", "object": item.destination})
        elif apply:
            bucket.copy_blob(
                source,
                bucket,
                item.destination,
                if_generation_match=0,
            )
            actions.append({"table": item.table, "action": "copy", "object": item.destination})
        else:
            actions.append({"table": item.table, "action": "would_copy", "object": item.destination})

    manifest_content = plan_as_json(plan).encode("utf-8")
    first_destination = plan[0].destination
    snapshot_root = first_destination.split("/", 3)[:3]
    manifest_name = "/".join(snapshot_root) + "/_manifest.json"
    manifest_blob = bucket.blob(manifest_name)
    manifest_md5 = _md5_bytes(manifest_content)
    if manifest_blob.exists(client=client):
        if not _matching_blob(manifest_blob, manifest_md5, None):
            raise BigQueryAnalysisError(
                f"Immutable snapshot manifest differs: {manifest_name}"
            )
        actions.append({"table": "_manifest", "action": "skip", "object": manifest_name})
    elif apply:
        manifest_blob.upload_from_string(
            manifest_content,
            content_type="application/json",
            if_generation_match=0,
        )
        actions.append({"table": "_manifest", "action": "upload", "object": manifest_name})
    else:
        actions.append({"table": "_manifest", "action": "would_upload", "object": manifest_name})
    return actions
