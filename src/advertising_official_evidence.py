"""Validated official evidence records for advertising discovery candidates."""

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Collection
from urllib.parse import urlsplit

if __package__:
    from .advertising_discovery import EvidenceStatus, normalize_discovery_url
else:
    from advertising_discovery import EvidenceStatus, normalize_discovery_url


class OfficialSourceType(str, Enum):
    BRAND_OFFICIAL = "BRAND_OFFICIAL"
    COMPANY_OFFICIAL = "COMPANY_OFFICIAL"
    PRODUCT_OFFICIAL = "PRODUCT_OFFICIAL"
    CAMPAIGN_OFFICIAL = "CAMPAIGN_OFFICIAL"


DISALLOWED_EVIDENCE_DOMAINS = {
    "blog.naver.com",
    "news.google.com",
    "search.naver.com",
}


def _utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("found_at must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError("found_at must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def official_evidence_id(
    candidate_id: str, official_source_url: str, source_type: OfficialSourceType | str
) -> str:
    normalized_url = normalize_discovery_url(official_source_url)
    normalized_type = OfficialSourceType(source_type).value
    digest = sha256(
        f"{candidate_id}\0{normalized_url}\0{normalized_type}".encode("utf-8")
    ).hexdigest()
    return f"official_evidence_{digest}"


def build_official_evidence(
    *,
    candidate: dict[str, Any],
    official_source_url: str,
    source_type: OfficialSourceType | str,
    found_at: str,
    verification_reason: str,
    official_domains: Collection[str],
) -> dict[str, Any]:
    """Build evidence only after its domain has been explicitly allowlisted."""
    if candidate.get("evidence_status") != EvidenceStatus.DISCOVERED.value:
        raise ValueError("Official evidence can only be added to a DISCOVERED candidate.")
    normalized_url = normalize_discovery_url(official_source_url)
    domain = (urlsplit(normalized_url).hostname or "").casefold()
    allowed = {item.strip().casefold() for item in official_domains if item.strip()}
    if domain in DISALLOWED_EVIDENCE_DOMAINS or domain not in allowed:
        raise ValueError("Official source domain must be explicitly allowlisted.")
    normalized_type = OfficialSourceType(source_type).value
    if not isinstance(verification_reason, str) or not verification_reason.strip():
        raise ValueError("verification_reason is required.")
    candidate_value = candidate.get("candidate_id")
    if not isinstance(candidate_value, str) or not candidate_value:
        raise ValueError("candidate_id is required.")
    return {
        "official_evidence_id": official_evidence_id(
            candidate_value, normalized_url, normalized_type
        ),
        "candidate_id": candidate_value,
        "official_source_url": normalized_url,
        "source_domain": domain,
        "source_type": normalized_type,
        "found_at": _utc_timestamp(found_at),
        "verification_status": EvidenceStatus.OFFICIAL_SOURCE_FOUND.value,
        "verification_reason": verification_reason.strip(),
    }


def transition_official_evidence(
    evidence: dict[str, Any],
    new_status: EvidenceStatus | str,
    *,
    verification_reason: str,
) -> dict[str, Any]:
    """Record a human-controlled evidence decision; no lookup occurs here."""
    current = EvidenceStatus(evidence.get("verification_status"))
    target = EvidenceStatus(new_status)
    if current != EvidenceStatus.OFFICIAL_SOURCE_FOUND or target not in {
        EvidenceStatus.VERIFIED,
        EvidenceStatus.REJECTED,
    }:
        raise ValueError(
            f"Invalid official evidence transition: {current.value} -> {target.value}."
        )
    if not isinstance(verification_reason, str) or not verification_reason.strip():
        raise ValueError("verification_reason is required.")
    updated = dict(evidence)
    updated["verification_status"] = target.value
    updated["verification_reason"] = verification_reason.strip()
    return updated
