# Contents Lakehouse

A data engineering project for collecting, normalizing, and analyzing artist, content, engagement, and commercial evidence with a Lakehouse architecture.

## 1. Project Goal

The goal of this project is to build a scalable **Content Intelligence Lakehouse** that tracks how artists, content, audience engagement, and advertising activities change over time.

The repository currently implements three connected data domains:

1. **YouTube:** channel and video metadata, metric snapshots, and growth-oriented analytical outputs.
2. **MediaWiki / artist metadata:** canonical artists, members, releases, and events with source lineage.
3. **Advertising:** discovery staging, official evidence, and canonical organization, brand, campaign, product, creative, market, and artist-participation relationships.

See [the data model](docs/DATA_MODEL.md) for table contracts and [the roadmap](docs/ROADMAP.md) for current milestone status. This overview intentionally does not duplicate them.

The long-term goal is to connect these domains and analyze relationships between:

**Artist Activity → Content Growth → Audience Engagement → Advertising Performance**

---

## 2. First Use Case: RESCENE

The first analysis target is **RESCENE**, a K-pop artist group.

Rather than collecting many artists from the beginning, the project uses one artist to build and validate its domain pipelines and relationships.

The YouTube pipeline starts from two channels relevant to RESCENE analysis:

* `@RESCENE_official`
* `@helloiamwoninicetomeetyou`

The second handle is treated as a related seed channel; the MVP does not assume
that it is an official corporate or artist channel.

The initial analysis will investigate:

* How RESCENE's content ecosystem changes over time
* How many related YouTube videos exist
* How individual content performs
* Daily changes in views, likes, and comments
* Growth patterns before and after major activities or releases
* Potential growth inflection points
* Differences between official and external content

---

## 3. Lakehouse Architecture

The project follows the Medallion Architecture.

```text
Data Sources
    │
    ▼
Bronze
Raw / immutable data
    │
    ▼
Silver
Cleaned / normalized data
    │
    ▼
Gold
Analytics-ready datasets
    │
    ▼
Analysis / Visualization / ML
```

The local environment is built around:

* MinIO
* Apache Iceberg
* Apache Spark
* DuckDB

The same logical storage boundaries support local execution and incremental cloud-processing expansion.

---

## 4. Development Strategy

Work is organized as bounded milestones with explicit completion criteria, validation, and reports. [The roadmap](docs/ROADMAP.md) is the canonical source for milestone order and status; durable engineering decisions are recorded under [`docs/adr/`](docs/adr/).

---

## 5. Engineering Principles

* Raw data must remain reproducible.
* Bronze data should be immutable.
* Pipelines should support incremental processing.
* Ingestion should be idempotent whenever possible.
* Data lineage and provenance should be traceable.
* Secrets must never be committed to Git.
* Local resource constraints should be measurable.
* Architecture should remain reproducible across environments.
* Working components should not be rewritten without a clear reason.

---

## Current Status

The local lakehouse foundation and the YouTube and Advertising domain milestones are implemented, alongside MediaWiki-backed artist metadata. RESCENE remains the initial analysis target. See [the roadmap](docs/ROADMAP.md) for the authoritative current and next milestone status.

---

## Cloud Bronze collection

Cloud collection entrypoints can run as short-lived Cloud Run Jobs that write
raw source responses to the pre-provisioned GCS Bronze bucket. Configure
`BRONZE_STORAGE_BACKEND=gcs`, `GCP_PROJECT_ID`, and `GCS_BUCKET` at runtime;
`GCS_BRONZE_BUCKET` remains a temporary compatibility alias. Authentication uses
the Cloud Run runtime identity through Application Default Credentials rather
than a service-account key file.

The collection-only commands are:

* `python src/run_youtube_collection.py`
* `python src/run_mediawiki_collection.py`
* `python src/run_advertising_collection.py`

## Local scheduled pipelines

The production-style one-shot entrypoints are intended for invocation through
their Windows CMD wrappers by Windows Task Scheduler:

* YouTube: `scripts/run_youtube_pipeline.cmd` — hourly at minute `05`
* MediaWiki: `scripts/run_mediawiki_pipeline.cmd` — daily at `06:10`
* Advertising: `scripts/run_advertising_pipeline.cmd` — daily at `06:30`

Docker Desktop must already be running when a task starts. Whether to select
**Run whether user is logged on or not** depends on whether the local Docker
Desktop installation is available in that session. Each task's action should
execute the corresponding `.cmd` wrapper. Logs are appended under `logs/`.

For all three tasks, set **If the task is already running** to **Do not start a
new instance**. The wrappers do not start Docker Desktop, retry failures, or
implement their own locking. Spark remains a short-lived Docker Compose job and
exits after each pipeline. Task Scheduler itself is not configured by this
project.
