# Contents Lakehouse Roadmap

Status values: `DONE`, `IN PROGRESS`, `PLANNED`.

## M01 — Foundation / Local Lakehouse

- **Objective:** Establish the local Bronze → Silver → Iceberg → Gold → DuckDB foundation.
- **Status:** DONE
- **Deliverables:** Local MinIO, Iceberg, Spark, and DuckDB service contracts; storage abstractions; medallion-layer conventions.
- **Completion criteria:** Local architecture and persistence boundaries are documented and exercised by repository pipelines and tests.
- **Report:** Not available; completed before milestone reporting was introduced.

## M02 — YouTube Pipeline

- **Objective:** Collect and model RESCENE YouTube data for reproducible channel, video, and metric analysis.
- **Status:** DONE
- **Deliverables:** YouTube Bronze capture; canonical Silver channel, video, and metric snapshots; hourly and 24-hour Gold transformations; collection entrypoints.
- **Completion criteria:** Repeated collection preserves raw lineage, stable video identity, snapshot history, and analytics-ready outputs.
- **Report:** Not available; completed before milestone reporting was introduced.

## M03 — Advertising Domain

- **Objective:** Model verified commercial relationships for tracked artists with evidence-preserving ingestion and canonical Advertising Silver outputs.
- **Status:** DONE
- **Deliverables:** Artist-first discovery staging; official-evidence adapters and models; deterministic canonical resolution; organization, brand, campaign, artist, campaign-brand, product taxonomy/tag, market, creative, and provenance relationships; Gold-ready projection.
- **Completion criteria:** Fixture-driven official evidence produces deterministic, validated canonical records while discovery/news evidence remains separate and unknown values remain null.
- **Report:** [M03 Advertising Domain](reports/M03-advertising-domain.md)

## M04 — Artist Activity Timeline

- **Objective:** Unify artist-related temporal events from existing domains into a common timeline contract suitable for later cross-domain analysis.
- **Status:** DONE
- **Deliverables:** A deterministic Silver timeline and evidence bridge, explicit YouTube/artist-event/Advertising projections, Iceberg merge definitions, temporal/reference validation, and focused regression tests.
- **Completion criteria:** Implemented domain events can be queried in chronological order with canonical artist identity, event time semantics, source lineage, and no invented relationships.
- **Report:** [M04 Artist Activity Timeline](reports/M04-artist-activity-timeline.md)

## M05 — Cross-domain Analytical Gold

- **Objective:** Provide analytics-ready views that combine completed domains through existing canonical relationships.
- **Status:** PLANNED — NEXT
- **Deliverables:** Cross-domain Gold contracts, incremental transformations, and query examples.
- **Completion criteria:** Validated Gold datasets answer defined cross-domain questions without display-name joins or duplicated raw data.
- **Report:** To be created when the milestone is completed.

## M06 — Cloud Processing Expansion

- **Objective:** Extend validated local processing patterns to managed cloud execution without changing domain meaning.
- **Status:** IN PROGRESS
- **Deliverables:** Existing GCS-capable storage and cloud collection entrypoints, followed by managed processing and operational validation.
- **Completion criteria:** Approved pipelines run repeatably in cloud processing, preserve medallion semantics, expose failures, and have documented rollback and cost controls.
- **Report:** To be created when the milestone is completed.

## M07 — Load / Cost / Performance Evaluation

- **Objective:** Measure workload capacity, operating cost, and performance before broader scale-out.
- **Status:** PLANNED
- **Deliverables:** Representative load profiles, benchmark results, cost measurements, and scaling recommendations.
- **Completion criteria:** Results are reproducible, bottlenecks are identified, and operational limits and cost assumptions are documented.
- **Report:** To be created when the milestone is completed.
