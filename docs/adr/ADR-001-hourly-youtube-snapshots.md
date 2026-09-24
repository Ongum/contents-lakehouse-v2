# ADR-001: Preserve hourly YouTube metric snapshots

## Status

Accepted — 2026-09-24

## Context

YouTube video statistics change over time. Replacing the latest values would prevent growth calculations, audit of collection timing, and reproducible 24-hour comparisons.

## Decision

Store append-oriented Silver metric snapshots keyed by stable video identity and observation time. Treat hourly collection as the operational target, preserve the raw Bronze response, and derive daily or 24-hour analytical outputs from snapshots rather than overwriting history.

## Consequences

Snapshot volume grows with collection frequency and requires deduplication for retried observations. In return, the lakehouse retains temporal history, source lineage, and the measurements required for incremental Gold transformations.

## References

- [Architecture](../ARCHITECTURE.md)
- [Data model](../DATA_MODEL.md)
- [Roadmap M02](../ROADMAP.md#m02--youtube-pipeline)
