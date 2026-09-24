# ADR-002: Keep News discovery separate from canonical Advertising data

## Status

Accepted — 2026-09-24

## Context

Search results and news articles are useful for discovering possible commercial relationships, but a celebrity mention does not prove a role such as model or ambassador. Treating discovery text as a canonical fact would create false artist, campaign, and relationship records.

## Decision

Store search responses in immutable Discovery Bronze and accepted leads in the staging candidate table. Promote no discovery candidate to canonical Advertising Silver until controlled official brand, company, product, or campaign evidence supports the relationship and lifecycle transition.

## Consequences

Discovery can optimize recall without weakening canonical evidence quality. Candidates may remain unresolved or be rejected, and multiple news URLs may refer to one eventual relationship. A future resolution process must preserve links from every candidate to official evidence.

## References

- [Advertising source feasibility](../ADVERTISING_SOURCE_FEASIBILITY.md)
- [Advertising data model](../DATA_MODEL.md#advertising-domain)
- [M03 report](../reports/M03-advertising-domain.md)
