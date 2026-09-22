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

## Quarantine and failure handling

The MVP uses the terms **quarantine** and **failure handling**. It does not have
a Kafka-style dead-letter queue (DLQ). Failure records and quarantined data are
stored alongside the existing lakehouse layers and processed by finite batch
jobs. This may evolve into a formal DLQ only if a later architecture requires
one.

The Local MVP uses one logical lakehouse storage namespace with these prefixes:

```text
bronze/
quarantine/silver/
quarantine/gold/
silver/
gold/
```

These prefixes define the logical boundaries. Exact physical bucket names and
Iceberg quarantine table names are implementation decisions.

### Failure classes

**Pipeline-level failures** prevent a task or run from completing safely. These
include an unavailable YouTube API, HTTP 403 or 429 responses, authentication
or quota failures, unavailable MinIO, and a failed Spark job. The current task
and hourly run fail with a non-success status and remain retryable. Data already
written successfully is not deleted; retries use the same source identity and
canonical keys to avoid duplicates.

For multi-channel collection, failure of either seed-channel request fails the
run. A payload already received successfully for the other channel remains a
valid Bronze object. The failed request does not produce an empty, synthetic,
or otherwise fake Bronze payload.

**Record-level failures** affect individual records while the surrounding task
can still complete safely. Examples include a malformed payload, invalid
timestamp, missing required identifier, or schema/type conversion failure.
Valid records continue to the target layer when their processing is independent
of the invalid record. Invalid records are written to quarantine with their
failure metadata and are never silently dropped.

If record-level isolation cannot guarantee a consistent target table, the
condition is promoted to a pipeline-level failure and the task fails.

### Failure flow by layer

```text
YouTube request
   ├─ success ───────────────> Bronze raw object
   └─ run/request failure ───> failure record; run fails; no fake Bronze object

Bronze raw object
   ├─ valid record ──────────> Silver canonical table
   └─ invalid record ────────> Silver quarantine + Bronze reference

Silver canonical record
   ├─ valid result ──────────> Gold analytics table
   └─ invalid input/result ──> Gold quarantine + Silver/source reference
```

- **Ingestion / Bronze:** preserve every successfully received raw payload in
  MinIO. Store request and run failures separately from Bronze source objects.
  When MinIO itself is unavailable, do not attempt to write failure or
  quarantine data to MinIO. Fail the task, emit a clear local error log or
  stderr message, and leave the task retryable.
- **Bronze to Silver:** store invalid records in a Silver quarantine area with
  a reference to the original immutable Bronze object. Commit valid records
  when they can be processed independently and safely.
- **Silver to Gold:** store invalid transformation inputs or results in a Gold
  quarantine area when record-level isolation is safe. Otherwise fail the Gold
  task. No failed record is silently filtered out.

For the Local MVP, request/run failure metadata and quarantine records use
MinIO objects or small Iceberg tables appropriate to their layer. This requires
no database, message broker, or always-running failure service.

### Minimal failure record contract

Every pipeline failure or quarantined record has the following metadata:

| Field | Meaning |
| --- | --- |
| `failure_id` | Stable unique identifier for this failure occurrence |
| `run_id` | Identifier of the hourly or manually triggered pipeline run |
| `pipeline_stage` | Failing stage, such as `ingestion`, `bronze_to_silver`, or `silver_to_gold` |
| `source_reference` | Source endpoint, Bronze object, or Silver record/table reference |
| `failed_at` | UTC timestamp when the failure was detected |
| `error_type` | Stable, machine-readable failure category |
| `error_message` | Short sanitized explanation with no credentials or secrets |
| `retry_count` | Number of reprocessing attempts for this failure |
| `status` | `unresolved`, `retryable`, or `resolved` |
| `payload_reference` | Location of the quarantined/raw payload when applicable; otherwise null |

The failure record stores a reference rather than duplicating a large payload.
`unresolved` means the cause still needs correction or classification;
`retryable` means the input is eligible for another attempt; and `resolved`
means reprocessing succeeded. Failure records are retained after resolution.

### Reprocessing rules

1. Reprocessing selects failure records with `retryable` status and reads the
   original input through `payload_reference` or `source_reference`.
2. Each attempt increments `retry_count` and records its outcome. An unfixed
   record stays quarantined; a successful attempt changes the failure status to
   `resolved` without deleting its history.
3. Successful reprocessing writes through the same Silver or Gold primary keys
   and incremental merge rules as a normal run. It must not append duplicate
   canonical records.
4. A pipeline-level retry may reuse its `run_id` for the same logical hourly
   run. A manually initiated reprocessing execution has its own run context but
   retains the original failure and source references.
5. Quarantine data is removed only through a separate, explicit retention
   decision; successful reprocessing alone does not erase it.

## Extension points

### Airflow after the end-to-end pipeline works

Airflow can later replace the host scheduler and manual sequencing with retries,
dependency management, backfills, and monitoring. The collector and Spark jobs
remain finite, idempotent tasks, so adding Airflow should not change storage
boundaries or table contracts. Airflow is deliberately absent from the MVP
Compose runtime. When introduced, Airflow may own task state, retry execution,
and operational logs; lakehouse failure records and quarantined payloads remain
the durable data-quality history.

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
