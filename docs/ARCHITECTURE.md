# Local MVP Architecture

## Scope and principles

The Local MVP supports one workload: collecting RESCENE-related YouTube data
every hour and making it available for local analysis. Collection starts from
`@RESCENE_official` and `@helloiamwoninicetomeetyou`. Both are relevant to the
analysis; only the first is assumed to be an official RESCENE channel. The
design favors reproducible batch runs and low idle memory use over distributed
or continuously running infrastructure.

Kafka and Airflow are not part of the MVP runtime. GCP is a future deployment
target, not a dependency of the local pipeline.

## Data flow

```text
                          hourly trigger
                                │
                                ▼
YouTube Data API ──> one-shot collector ──> Bronze objects in MinIO
                                                   │
                                                   ▼
                                      on-demand Spark transform
                                                   │
                                      ┌────────────┴────────────┐
                                      ▼                         ▼
                               Silver Iceberg             Gold Iceberg
                               normalized data         analytics-ready data
                                      │                         │
                                      └────────────┬────────────┘
                                                   ▼
                                                DuckDB
                                             local analysis
```

1. A lightweight host scheduler invokes the collector once per hour. Manual
   invocation remains possible during development.
2. The collector calls the YouTube API and appends the raw response plus source
   and ingestion metadata to Bronze in MinIO.
3. Spark runs as a finite batch job after collection or on demand. It reads new
   Bronze objects, incrementally updates Silver Iceberg tables, and derives the
   required Gold tables.
4. DuckDB reads Silver or Gold for local exploration. Normal analysis should
   prefer Gold.

A failed run is retried as a batch. No message broker or streaming path is
needed for an hourly, single-artist workload.

## Component responsibilities

| Component | MVP responsibility | Runtime behavior |
| --- | --- | --- |
| Docker Compose | Define reproducible local services, networks, volumes, and configuration boundaries | Starts only the services needed for a run or analysis session |
| MinIO | Durable object storage for immutable Bronze payloads and the files underlying local Iceberg tables | Persistent service with data on a Docker volume |
| Collector | Fetch channel, video, and metric data for the configured RESCENE-related seed channels and write Bronze records | One-shot process invoked hourly; exits after success or failure |
| Apache Spark | Parse, normalize, deduplicate, preserve lineage, and incrementally build Silver and Gold Iceberg tables | On-demand batch process; no idle Spark cluster |
| Apache Iceberg | Provide transactional table metadata and table evolution for canonical Silver and derived Gold data | Table format, not a continuously running compute engine |
| DuckDB | Query the local lakehouse for validation and analysis, especially Gold hourly and rolling 24-hour growth | Started only for a query or interactive session |

Secrets such as the YouTube API key are supplied through environment variables
and are never stored in images, Compose files, or lakehouse data.

## Runtime strategy

The default cadence is one collection attempt per hour. The stored
`observed_at` value is the actual UTC observation time, not the scheduled hour.
This preserves delayed runs and multiple observations within a day.

To fit a limited-memory machine:

- keep only MinIO running when persistent object access is required;
- run the collector and Spark as short-lived Compose jobs;
- use local-mode Spark with explicit CPU and memory limits;
- do not keep Spark workers, DuckDB, Airflow, or a message broker running;
- process new Bronze inputs incrementally instead of rebuilding all history.

Docker Compose provides a repeatable environment, but it is not the workflow
orchestrator. During the MVP, a host scheduler or a manual command triggers the
same idempotent batch entry point.

## Medallion boundaries

### Bronze — raw source ownership

Bronze owns append-only YouTube API responses and raw curated event inputs in
MinIO. Each object includes ingestion time, source/endpoint metadata, request
context, and a reproducible identity. Bronze preserves source fidelity and does
not enforce the relational model.

### Silver — canonical data ownership

Silver owns the normalized Iceberg tables defined in `DATA_MODEL.md`:
`artist`, `youtube_channel`, `youtube_video`, `video_metrics_snapshot`, and
`artist_event`. Spark deduplicates records, enforces stable keys, normalizes all
timestamps to UTC, and retains lineage to Bronze.

### Gold — analytics ownership

Gold owns only reusable analytics-ready Iceberg tables or views derived from
Silver. For the MVP this includes hourly and rolling 24-hour video growth with
artist, channel, and event context. Gold does not copy raw payloads or create
new entity identities.

## Extension points

### Airflow after the end-to-end pipeline works

Airflow can later replace the host scheduler and manual sequencing with retries,
dependency management, backfills, and monitoring. The collector and Spark jobs
remain finite, idempotent tasks, so adding Airflow should not change storage
boundaries or table contracts. Airflow is deliberately absent from the MVP
Compose runtime.

### Future GCP migration

The migration should preserve the Bronze/Silver/Gold contracts and Iceberg
table model. MinIO object paths can map to cloud object storage, and local Spark
execution can map to managed or serverless Spark. Scheduling and analytics can
then move to suitable GCP services after local workloads and resource usage are
measured. No GCP service is required or emulated in the Local MVP.

## Explicit exclusions

- Kafka or any streaming broker
- Airflow in the MVP runtime
- always-running Spark workers
- GCP resources or cloud-specific data models
- data sources other than the current RESCENE YouTube scope
