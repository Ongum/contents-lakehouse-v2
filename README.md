# Contents Lakehouse

A data engineering project for collecting, storing, and analyzing content ecosystem data using a Lakehouse architecture.

## 1. Project Goal

The goal of this project is to build a scalable **Content Intelligence Lakehouse** that tracks how artists, content, audience engagement, and advertising activities change over time.

The project focuses on three data domains:

1. **Artist Data**

   * Artist and member information
   * Releases
   * Activities and events

2. **Content & Engagement Data**

   * YouTube videos
   * Spotify releases and metrics
   * Content publication history
   * Views, likes, comments, and other engagement metrics
   * Daily snapshots for time-series analysis

3. **Advertising Data**

   * Brand and product information
   * Advertising campaigns
   * Artist–brand relationships
   * Campaign and product performance

The long-term goal is to connect these domains and analyze relationships between:

**Artist Activity → Content Growth → Audience Engagement → Advertising Performance**

---

## 2. First Use Case: RESCENE

The first analysis target is **RESCENE**, a K-pop artist group.

Rather than collecting many artists from the beginning, the first version of the project focuses on building a complete end-to-end pipeline for a single artist.

The MVP starts from two YouTube channels relevant to RESCENE analysis:

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

Once the pipeline is stable, additional artists and platforms can be added.

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

The initial local environment will be built around:

* MinIO
* Apache Iceberg
* Apache Spark
* DuckDB

The architecture will later be migrated and benchmarked on GCP.

---

## 4. Development Strategy

Development is divided into incremental stages.

### Phase 1 — Local MVP

Build a complete pipeline for RESCENE YouTube data.

```text
YouTube API
    ↓
Bronze
    ↓
Silver
    ↓
Iceberg
    ↓
Daily Snapshot
    ↓
DuckDB
    ↓
Analysis
```

### Phase 2 — Data Expansion

Add additional sources such as:

* Spotify
* External YouTube content
* Artist activities and events

### Phase 3 — GCP Migration

Migrate the local architecture to GCP while preserving the same logical data model.

Compare local and cloud environments using measurable workloads.

### Phase 4 — Scale & Reliability

Perform controlled load tests and measure:

* Processing time
* Throughput
* Memory usage
* Query performance
* Failure and recovery behavior
* Cloud cost

### Phase 5 — Advertising Intelligence

Connect artist and content data with advertising and product-performance data.

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

**Stage:** Project initialization

**Current target:** RESCENE

**Current milestone:**

> Build a reproducible end-to-end YouTube data pipeline for RESCENE in the local Lakehouse environment.
