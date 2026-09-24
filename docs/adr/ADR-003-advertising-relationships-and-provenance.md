# ADR-003: Separate canonical Advertising relationships from provenance

## Status

Accepted — 2026-09-24

## Context

Advertising facts can be supported by several sources, and one source can support several fields. Campaigns may involve multiple brands and zero or more artists. A single `advertising_campaign.brand_id` cannot represent all valid campaign-brand relationships, while evidence URLs embedded in canonical rows cannot express field-level support cleanly.

## Decision

Represent domain facts through normalized canonical entities and relationship tables. Use `campaign_artist` for verified artist participation, `campaign_brand` for the canonical many-to-many campaign-brand relationship, and dedicated product, taxonomy/tag, market, creative, and campaign-product relationships. Keep `advertising_campaign.brand_id` only as a backward-compatible primary-brand projection. Store record-level evidence in `source_evidence` and field-level assertions in `canonical_field_evidence`; provenance does not replace canonical foreign keys.

Unknown relationships remain absent or null. A campaign with no artist is valid, and no fake artist or placeholder ID is created.

## Consequences

Consumers should use `campaign_brand` for complete brand membership and may use `advertising_campaign.brand_id` only for legacy primary-brand behavior. Evidence can evolve or multiply without changing canonical identity, and canonical records remain queryable without parsing source payloads. Persistence must validate foreign-key-style references and avoid duplicate relationship assignments.

## References

- [Advertising data model](../DATA_MODEL.md#advertising-domain)
- [M03 report](../reports/M03-advertising-domain.md)
- [Roadmap M03](../ROADMAP.md#m03--advertising-domain)
