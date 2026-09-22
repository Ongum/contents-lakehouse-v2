# AGENTS.md

## Goal

Build a Content Intelligence Lakehouse.

Current scope:
**RESCENE YouTube data only.**

Do not expand scope unless explicitly requested.

## Architecture

```text
API → Bronze → Silver → Iceberg → Gold → DuckDB
```

Local stack:

* MinIO
* Apache Iceberg
* Spark
* DuckDB

Cloud migration to GCP comes later.

## Medallion Rules

### Bronze

* Preserve raw source data.
* Append rather than overwrite when possible.
* Store ingestion timestamp and source metadata.

### Silver

* Clean and normalize Bronze data.
* Use stable internal IDs.
* Deduplicate records.
* Preserve lineage to the source.

### Gold

* Store analytics-ready datasets.
* Prefer incremental transformations.
* Do not duplicate raw data unnecessarily.

## Engineering Rules

* Prefer simple solutions.
* Preserve working code.
* Do not refactor unrelated files.
* Do not add dependencies unless necessary.
* Never commit credentials or API keys.
* Use environment variables for secrets.
* Pipelines should be idempotent where practical.
* Keep resource usage measurable.
* Add tests for important transformations.

## AI Working Rules

Before changing code:

1. Read this file.
2. Read only the relevant documentation/files.
3. Inspect existing implementation before creating new code.
4. Make the smallest change that completes the task.

Do not:

* redesign the entire architecture without request;
* create unnecessary abstractions;
* rewrite working modules without reason;
* expand to Spotify, advertising, ML, or GCP unless requested;
* generate large documentation unless requested.

After changes, report only:

* changed files;
* what change
