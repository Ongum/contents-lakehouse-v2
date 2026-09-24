# M04 — Artist Activity Timeline

## Objective

Unify explicit artist-related temporal facts from implemented domains into a common timeline contract suitable for later cross-domain analysis.

## Status

`DONE`. The additive timeline projection, persistence contract, data-quality validation, focused tests, and documentation are complete without changing existing canonical IDs or domain grains.

## Delivered

- `artist_activity_timeline` at one artist × supported source-domain temporal fact.
- `artist_activity_timeline_evidence` for zero-to-many official Advertising evidence references.
- Deterministic projections for YouTube video publication, existing artist events, explicit campaign announcement/start/end facts, and official-evidence publication.
- Additive Silver Iceberg definitions and idempotent merge keys; no live migration or production write.
- Chronological in-memory output for downstream inspection and future event-window work.

## Engineering Decisions

The timeline is a Silver integration projection that references existing domain identities. It does not replace business models or create a new master entity. Event identity excludes mutable labels and timestamps so corrected temporal values update the same source fact. UUID5 input uses a canonical compact JSON array, preventing delimiter ambiguity without changing any pre-existing domain ID. Advertising publication and effective times remain separate event types and semantics.

No new ADR was required because these choices apply the existing canonical-relationship, provenance, stable-ID, and medallion rules.

## Data Quality / Reliability

Validation covers deterministic IDs, artist and source references, duplicate or conflicting logical events, UTC timestamps, date-boundary precision, supported source-domain/event-type combinations, evidence assignments, and idempotent projection. Nullable observation and provenance fields do not invalidate a supported temporal fact, while absent event times produce no timeline row.

## Validation

On 2026-09-24, 58 focused and regression tests passed across the timeline,
YouTube Silver, MediaWiki Silver, official Advertising evidence, and
Advertising Silver suites. `python -m compileall -q src tests`, internal
Markdown link validation, and `git diff --check` also passed.

## Known Limitations

- Advertising relationship effective dates are not projected because the current canonical `campaign_artist` table does not store them; campaign dates remain campaign facts.
- Existing date-only source fields are represented by a UTC day boundary plus mandatory `DATE` precision.
- The projection is implemented and persistable but this milestone performs no live Iceberg migration or write.
- Event windows, statistical comparison, and causal interpretation belong to later analytical work.

## Outcome

The M04 completion criteria are met. Supported domain facts can be projected in
chronological order with canonical artist identity, explicit temporal semantics,
source references, and official-evidence provenance without inventing missing
relationships or timestamps.

## Next Milestone

The next milestone is [M05 — Cross-domain Analytical Gold](../ROADMAP.md#m05--cross-domain-analytical-gold).
