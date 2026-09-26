# ADR-004 — Advertising observations and bounded YouTube failure isolation

Status: Accepted for local implementation, 2026-09-25.

## Context

Content-addressed Advertising documents retained distinct versions but lost
repeated observations and reversions. YouTube aborted independent collection
after one unavailable or malformed video, leaving avoidable historical gaps.

## Decision

Keep Advertising document keys and canonical Silver IDs unchanged. Add immutable
observation objects referencing durable content versions. Their identity includes
source, run ID, and normalized observation time; exact replay is idempotent and
conflicting replay is rejected. Latest state follows observation chronology.
Legacy documents contribute their single known original observation.

Observation metadata is returned separately from the original content envelope.
Latest-state selection uses observation time, but the content retrieval time
passed to existing Silver transformations remains unchanged. A repeat observation
must not move an existing content-keyed metric or evidence fact to a new time.
Reference resolution and observation recovery validate stored content integrity.

Write content before observation. New content envelopes carry a contract marker,
so incomplete writes do not become latest state. Recovery can read a retained
document and call `write_observation(record, content_reference)` with its original
context. Replaying an already completed observation is safe. For reused content,
the caller must retain/replay the failed occurrence's original context; refetching
with a new run/time records a new occurrence, not a recovered historical one.
There is no cross-object transaction or generalized recovery engine.

YouTube isolates failures by item, request batch, and channel. Discovery page
failures retain earlier discovered IDs. Structured diagnostics are persisted
separately from Bronze; partial collection returns nonzero only after independent
work finishes. Storage failures remain fatal. Raw responses keep original run
observation time for later Bronze replay; refetching cannot backfill missed counts.

## Consequences

Two content versions can support arbitrarily many small observations. Observation
listing adds object-store reads/writes proportional to collection history; this
phase does not introduce indexing or retention changes. Atomic create semantics
use the existing MinIO conditional-write and GCS generation-guard adapters.
No infrastructure, production data, canonical IDs, Gold tables, or source scope
changes are authorized by this decision. M05 remains blocked.
