# M03 — Advertising Domain

## Objective

Create an evidence-preserving Advertising domain that represents verified commercial relationships for tracked artists while keeping discovery signals separate from canonical facts.

## Status

`DONE` for the fixture-driven canonical Advertising domain. This status excludes generalized campaign entity resolution, broad production crawling, automatic official verification, live infrastructure changes, and Gold analytical calculations.

## Delivered

- Separate adapters for Google News KR discovery and fixture-driven official brand/company evidence, with `OfficialAdvertisingEvidence` as the reusable evidence contract.
- Deterministic resolution into canonical advertiser organization, brand, campaign, artist participation, campaign-brand, product, taxonomy/tag, market, creative, and source-evidence records.
- Explicit canonical relationships, including optional `campaign_artist` participation and many-to-many `campaign_brand`; `advertising_campaign.brand_id` remains a compatibility projection.
- Hierarchical product categories, separate many-to-many product tags, normalized markets, and period precision fields without inferring missing values for the existing RESCENE campaign.
- Record and field-level provenance that keeps canonical facts distinct from their supporting evidence.
- Null semantics that preserve unknown or unsupported values instead of generating placeholder artists, products, markets, tags, or dates.
- A Gold-ready advertising projection without implementing Gold calculations in this milestone.
- Discovery/news candidates kept in staging and Discovery Bronze, separate from official evidence and canonical Advertising Silver.
- Feasibility findings for KOBACO AiSAC, KOBACO Public Data Portal dataset 15105570, and official brand/company sources. KOBACO is supplementary/reference evidence rather than authority for artist commercial roles.
- Rights-aware source handling: public visibility is not treated as permission to redistribute creative media, and unresolved commercial-reuse terms remain a production limitation.

The canonical relationships are maintained in [DATA_MODEL.md](../DATA_MODEL.md). Source findings and rights constraints are maintained in [ADVERTISING_SOURCE_FEASIBILITY.md](../ADVERTISING_SOURCE_FEASIBILITY.md).

## Engineering Decisions

- [ADR-002](../adr/ADR-002-news-advertising-domain-boundary.md) keeps News discovery evidence outside the Advertising canonical model until official verification.
- [ADR-003](../adr/ADR-003-advertising-relationships-and-provenance.md) records the canonical relationship, provenance, and campaign-brand compatibility decisions.

Candidate identity represents discovery evidence identity, not a canonical campaign. Multiple article URLs can remain distinct candidates for one apparent relationship until a future entity-resolution step.

## Data Quality / Reliability

Canonical IDs and candidate/evidence IDs are deterministic. Persistence validates relationship references and duplicate assignments, repeated ingestion is idempotent at established keys, source and field provenance are retained, and unknown values remain null or unassigned. Campaigns with zero artist relationships remain valid, and discovery linkage does not create `campaign_artist` rows.

## Validation

The latest implementation validation on 2026-09-24 passed 83 relevant Advertising, discovery, collection, and pipeline tests. Python compilation and `git diff --check` also passed for that implementation state. This documentation update does not rerun application tests.

## Known Limitations

- Official-source lookup and verification remain controlled operations; broad automatic verification is not enabled.
- Generalized resolution of multiple evidence candidates into one real-world campaign is intentionally deferred.
- Current official-source support is fixture-driven and source-specific; production collection requires separate access, rights, and stability approval.
- KOBACO structured data does not establish artist roles, brands, products, or campaigns reliably enough to be a canonical relationship source.
- Creative-media redistribution rights and some source terms require clarification before production dependency or monetized reuse.
- Existing live Iceberg data is not migrated by this milestone, and no GCP resources are changed.

## Outcome

The M03 completion criteria are met for the repository's fixture-driven canonical Advertising domain. The milestone is `DONE`; this status does not claim every source is production-ready or live official verification is automated.

## Next Milestone

The next milestone is [M04 — Artist Activity Timeline](../ROADMAP.md#m04--artist-activity-timeline).
