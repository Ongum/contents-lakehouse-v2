"""Advertising domain vocabularies and explainable data-quality assessment."""

import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any


class AuthorityLevel(str, Enum):
    OFFICIAL = "OFFICIAL"
    STRUCTURED_PUBLIC_SOURCE = "STRUCTURED_PUBLIC_SOURCE"
    PLATFORM_SOURCE = "PLATFORM_SOURCE"
    DERIVED = "DERIVED"


class QualitySeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class DataQualityIssue:
    severity: QualitySeverity
    rule: str
    record_reference: str
    message: str


def source_evidence_id(source_name: str, source_record_id: str, content_hash: str) -> str:
    """Identify one source observation without relying on canonical entities."""
    values = (source_name.strip(), source_record_id.strip(), content_hash.strip())
    if not all(values) or not re.fullmatch(r"[0-9a-f]{64}", values[2]):
        raise ValueError("Source evidence identity requires source, record ID, and SHA-256 hash.")
    digest = sha256("\0".join(values).encode("utf-8")).hexdigest()
    return f"source_evidence_{digest}"


def assess_advertising_quality(result: Any) -> list[DataQualityIssue]:
    """Return explainable non-mutating quality findings for one Silver batch."""
    issues: list[DataQualityIssue] = []
    evidence_ids = {row["source_evidence_id"] for row in result.source_evidence}
    product_keys: dict[tuple[str, str], str] = {}
    for row in result.products:
        key = (row["brand_id"], " ".join(row["product_name"].casefold().split()))
        if key in product_keys and product_keys[key] != row["product_id"]:
            issues.append(DataQualityIssue(
                QualitySeverity.WARNING,
                "duplicate_canonical_product",
                row["product_id"],
                f"Same normalized brand/product name as {product_keys[key]}.",
            ))
        product_keys[key] = row["product_id"]
    for row in result.markets:
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,31}", row["market_code"]):
            issues.append(DataQualityIssue(
                QualitySeverity.ERROR, "invalid_market_code", row["market_id"],
                "market_code must be an uppercase governed code.",
            ))
    source_keys: set[tuple[str, str]] = set()
    for row in result.source_evidence:
        key = (row["source_name"], row.get("source_record_id") or "")
        if key[1] and key in source_keys:
            issues.append(DataQualityIssue(
                QualitySeverity.ERROR, "duplicate_source_identifier",
                row["source_evidence_id"], "Duplicate source record identifier.",
            ))
        source_keys.add(key)
    for row in result.campaign_artists:
        supported = any(
            item["entity_type"] == "CAMPAIGN_ARTIST"
            and item["entity_id"] == row["campaign_artist_id"]
            and item["source_evidence_id"] in evidence_ids
            for item in result.canonical_field_evidence
        )
        if not supported:
            issues.append(DataQualityIssue(
                QualitySeverity.UNRESOLVED, "verified_fact_missing_evidence",
                row["campaign_artist_id"],
                "Artist relationship has no field-level source evidence in this batch.",
            ))
    grouped: dict[tuple[str, str, str], set[str | None]] = {}
    for row in result.canonical_field_evidence:
        key = (row["entity_type"], row["entity_id"], row["field_name"])
        grouped.setdefault(key, set()).add(row.get("asserted_value"))
    for key, values in grouped.items():
        if len(values) > 1:
            issues.append(DataQualityIssue(
                QualitySeverity.WARNING, "conflicting_canonical_values",
                ":".join(key), "Sources assert different values; selection must be explained.",
            ))
    return issues
