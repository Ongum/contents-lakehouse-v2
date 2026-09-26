# Contents Lakehouse Architecture

## Scope and principles

The lakehouse supports implemented YouTube, MediaWiki/artist-metadata, and
Advertising workloads through shared Bronze, Silver, Iceberg, and Gold
boundaries. RESCENE remains the initial analysis target. Domain schemas and
relationships are defined in [DATA_MODEL.md](DATA_MODEL.md), while milestone
status is maintained in [ROADMAP.md](ROADMAP.md).

The local runtime uses reproducible finite batch jobs and favors low idle
memory use over distributed or continuously running infrastructure. The hourly
YouTube pipeline remains the reference implementation: it starts from
`@RESCENE_official` and `@helloiamwoninicetomeetyou`, and only the first is
assumed to be an official RESCENE channel.

Kafka and Airflow are not part of the local runtime. GCP is not a dependency of
local processing; GCS-capable Bronze collection is an additive deployment path.

## Data flow

```text
YouTube API ───────────┐
MediaWiki API ─────────┼─> one-shot collectors ─> source-specific Bronze
Advertising sources ──┘                              │
                                                    ▼
                                           finite batch transforms
                                                    │
                                       ┌────────────┴────────────┐
                                       ▼                         ▼
                                Silver Iceberg             Gold Iceberg
                                canonical data          analytical data
                                       │                         │
                                       └────────────┬────────────┘
                                                    ▼
                                                 DuckDB
                                              local analysis
```

1. A lightweight host scheduler invokes each enabled domain collector at its
   configured cadence. Manual invocation remains possible during development.
2. Collectors append raw responses plus source and ingestion metadata to their
   source-specific Bronze namespaces in MinIO or the configured object store.
3. Finite batch transforms read new Bronze objects, incrementally update Silver
   Iceberg tables, and derive implemented Gold outputs.
4. DuckDB reads Silver or Gold for local exploration. Normal analysis should
   prefer Gold.

A failed run is retried as a batch. No message broker or streaming path is
needed for the current bounded workloads.

## Component responsibilities

| Component | MVP responsibility | Runtime behavior |
| --- | --- | --- |
| Docker Compose | Define reproducible local services, networks, volumes, and configuration boundaries | Starts only the services needed for a run or analysis session |
| MinIO | Durable object storage for immutable Bronze payloads and the files underlying local Iceberg tables | Persistent service with data on a Docker volume |
| Collectors | Fetch source-native YouTube, MediaWiki, and Advertising payloads and write source-specific Bronze records | One-shot processes invoked at the configured cadence; exit after success or failure |
| Batch transforms | Parse, normalize, deduplicate, preserve lineage, and incrementally build implemented Silver and Gold Iceberg tables | Finite jobs; no idle compute cluster |
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

Bronze owns append-only source responses and raw curated inputs in the
configured object store. Each object includes ingestion time, source/endpoint
metadata, request context, and a reproducible identity. Source-specific
namespaces keep discovery evidence, verified Advertising evidence, MediaWiki,
and YouTube payloads distinct. Bronze preserves source fidelity and does not
enforce the relational model.

### Silver — canonical data ownership

Silver owns the normalized Iceberg tables defined in
[DATA_MODEL.md](DATA_MODEL.md). Domain transforms deduplicate records, enforce
stable keys, normalize timestamps according to the documented semantics, and
retain lineage to Bronze or official source evidence.

### Gold — analytics ownership

Gold owns only reusable analytics-ready Iceberg tables or views derived from
Silver. Implemented outputs include hourly and rolling 24-hour video growth and
the Advertising commercial-intelligence projection. Gold does not copy raw
payloads or create new entity identities. The planned cross-domain analytical
milestone is not represented as completed here.

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
run after independent collection has finished. YouTube isolates invalid or
unavailable video items, failed detail batches, and failed channels. A failed
uploads page stops pagination for that playlist but already discovered IDs are
still collected. Successful raw responses remain valid Bronze objects. Failed
requests never produce synthetic Bronze payloads or invented metrics.

YouTube collection diagnostics are immutable JSON objects under
`failures/youtube/collection/`, separate from raw Bronze. They retain run and
observation context, resource/request parameters without credentials, item/video
identity where available, failure type, recovery status, and an exact Bronze
reference when a response was persisted. Partial runs return nonzero after
collection; the end-to-end entrypoint does not advance downstream processing.
If raw or diagnostic persistence fails, collection fails immediately. Replaying
stored responses preserves their original observation time; a new API request
is a new observation and cannot reconstruct a missed historical metric.

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

### Advertising domain boundary

Advertising is a commercial-facts domain assembled from complementary sources;
it is not a database of media coverage. Each source owns an immutable Bronze
namespace and retains its native payload contract:

```text
bronze/advertising/kobaco/             (supplementary/reference; rights-limited)
bronze/advertising/official_brand/     (source-specific official pages)
bronze/advertising/official_product/   (source-specific official pages)
bronze/advertising/meta/               (future; feasibility not confirmed)
              │
              ▼
source_evidence + unresolved source-native records
              │ deterministic identifiers / explicit aliases / review
              ▼
Advertising Silver entities and relationships
              │
              ▼
commercial-intelligence Gold marts
```

Bronze preserves `source`, `source_record_id`, `collected_at`, sanitized request
context, raw payload, and content hash. Source payloads do not share one forced
raw schema. Silver owns commercial entities, creatives, relationships, and
reusable evidence references; Gold owns analytical grains.

Advertising document capture now separates immutable content versions from
immutable collection observations. Existing `content_hash=.../document.json`
objects stay unchanged. Small `observations/<observation_id>.json` objects in
the same source directory reference those content objects, so A → B → A stores
two full payloads and three observations. Latest state is selected by normalized
UTC observation time, with object key as a deterministic tie-breaker for equal
timestamps, rather than by the first capture time of each content version.

Content is written before its observation using create-only operations. A
failed observation write fails the collection. For newly created content, its
envelope contains the original run/time context needed to retry
`write_observation`; reused content requires the caller to retain the failed
occurrence's context. Latest readers keep observation metadata separate from
the original content envelope to preserve existing Silver timestamp semantics.
New-contract content without an observation is not a completed latest state.
Legacy content envelopes remain readable as their single known observation;
missing historical repeats are never invented. See
[ADR-004](adr/ADR-004-foundation-observation-history.md) for identity and recovery.

Google News RSS is a discovery source and remains outside canonical Advertising
facts. Its immutable discovery responses and staging candidates may lead to
official-source review, but only verified official evidence can establish a
canonical commercial relationship. A separate News domain and News NLP are not
implemented.

### Airflow as an optional orchestrator

Airflow may later replace the host scheduler and manual sequencing with retries,
dependency management, backfills, and monitoring. The collector and Spark jobs
remain finite, idempotent tasks, so adding Airflow should not change storage
boundaries or table contracts. Airflow is deliberately absent from the MVP
Compose runtime. When introduced, Airflow may own task state, retry execution,
and operational logs; lakehouse failure records and quarantined payloads remain
the durable data-quality history.

### Cloud processing expansion

GCS-capable collectors preserve the same Bronze contracts used locally. Further
managed processing must preserve the Bronze/Silver/Gold contracts and Iceberg
table model; local finite-batch execution can map to managed or serverless
compute after workloads and resource usage are measured. No GCP service is
required or emulated for local execution.

## Explicit exclusions

- Kafka or any streaming broker
- Airflow in the local runtime
- always-running Spark workers
- managed GCP processing resources in the local runtime
- cloud-specific canonical data models
- completed cross-domain analytical Gold marts
