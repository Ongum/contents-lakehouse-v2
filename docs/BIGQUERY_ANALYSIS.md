# BigQuery analysis foundation

## Scope

BigQuery is a read-only analytical projection over a reviewed GCS Silver
snapshot. It does not replace the canonical local Silver Iceberg tables and it
does not read Bronze directly. The first snapshot covers the 18 tables in
`data/eda/youtube_september_2026/manifest.json` plus the current cloud-managed
Mnet Plus `artist_activity` table.

Each analyst-facing table has two BigQuery objects:

- `<table>_external` reads immutable Parquet files from GCS.
- `<table>` is the stable view analysts query. It explicitly projects the
  recorded columns and normalizes Parquet-specific shapes where required.

The `youtube_video` view converts Spark's nested Parquet list representation
for `tags` into a normal BigQuery `ARRAY<STRING>`.

## Modules

| Module | Responsibility |
| --- | --- |
| `src/bigquery_analysis.py` | Validate the EDA manifest, build the 19-table immutable snapshot plan, and render BigQuery DDL. It performs no cloud writes. |
| `src/bigquery_snapshot.py` | Publish local Parquet and copy the live Mnet Plus Parquet into one create-only GCS snapshot. Identical reruns are skipped; conflicting objects fail. |
| `scripts/prepare_bigquery_analysis.py` | CLI for reviewing the upload plan or generating SQL. It never applies SQL. |
| `scripts/publish_bigquery_snapshot.py` | Dry-run the GCS publication by default; `--apply` is required for writes. |
| `tests/test_bigquery_analysis.py` | Lock the 19-table coverage, safe identifiers, snapshot paths, and `tags` normalization. |

## Prepared workflow

Set `GCP_PROJECT_ID`, `GCS_BUCKET`, `BIGQUERY_DATASET`, and
`BIGQUERY_LOCATION`. Set `BIGQUERY_SNAPSHOT_ID` once for a publication, using a
UTC identifier such as `20261007T120000Z`, and reuse that exact value for plan,
publish, and DDL generation. The current intended values are project
`fandom-data-lakehouse`, bucket `fandom-data-lakehouse-bronze`, dataset
`contents_lakehouse`, and location `asia-northeast1`.

Review the immutable upload plan:

```powershell
python scripts/prepare_bigquery_analysis.py --format plan --output analysis/bigquery-snapshot-plan.json
```

Generate reviewable SQL without changing BigQuery:

```powershell
python scripts/prepare_bigquery_analysis.py --format sql --output analysis/contents-lakehouse.sql
```

Dry-run the GCS publication. This reads GCS metadata but does not write:

```powershell
python scripts/publish_bigquery_snapshot.py
```

The following two actions change cloud state and require explicit approval at
execution time:

1. Publish the immutable snapshot with
   `python scripts/publish_bigquery_snapshot.py --apply`.
2. Apply the generated SQL with the `bq` CLI in `asia-northeast1`.

Apply the SQL only after every planned Parquet object and `_manifest.json` is
present. `CREATE OR REPLACE` updates external-table definitions and logical
views but does not load data into BigQuery storage.

## Analysis examples

```sql
-- Table inventory and column contracts
SELECT table_name, column_name, data_type, is_nullable
FROM `fandom-data-lakehouse.contents_lakehouse.INFORMATION_SCHEMA.COLUMNS`
WHERE NOT ENDS_WITH(table_name, '_external')
ORDER BY table_name, ordinal_position;

-- Rows available per key fact table
SELECT 'youtube_video' AS table_name, COUNT(*) AS row_count
FROM `fandom-data-lakehouse.contents_lakehouse.youtube_video`
UNION ALL
SELECT 'video_metrics_snapshot', COUNT(*)
FROM `fandom-data-lakehouse.contents_lakehouse.video_metrics_snapshot`
UNION ALL
SELECT 'artist_activity', COUNT(*)
FROM `fandom-data-lakehouse.contents_lakehouse.artist_activity`;

-- Latest YouTube observation coverage
SELECT
  COUNT(DISTINCT video_id) AS videos,
  MIN(observed_at) AS first_observation,
  MAX(observed_at) AS latest_observation
FROM `fandom-data-lakehouse.contents_lakehouse.video_metrics_snapshot`;
```

External-table queries scan GCS Parquet on demand. Use column selection and
timestamp filters to control bytes scanned. Materialized/native BigQuery tables,
scheduled queries, partitioning, and Gold marts remain later cost/performance
decisions rather than part of this foundation.
