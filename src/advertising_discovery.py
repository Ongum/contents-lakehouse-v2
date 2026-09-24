"""KR-only advertising discovery candidates and evidence lifecycle."""

from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if __package__:
    from .advertising_collection import is_sensitive_name
else:
    from advertising_collection import is_sensitive_name


TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


class EvidenceStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    OFFICIAL_SOURCE_FOUND = "OFFICIAL_SOURCE_FOUND"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


ALLOWED_TRANSITIONS = {
    EvidenceStatus.DISCOVERED: {
        EvidenceStatus.OFFICIAL_SOURCE_FOUND,
        EvidenceStatus.REJECTED,
    },
    EvidenceStatus.OFFICIAL_SOURCE_FOUND: {
        EvidenceStatus.VERIFIED,
        EvidenceStatus.REJECTED,
    },
    EvidenceStatus.VERIFIED: set(),
    EvidenceStatus.REJECTED: set(),
}


def _utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("discovered_at must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError("discovered_at must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("discovery_source is required.")
    normalized = value.strip().lower()
    if not normalized.replace("_", "").replace("-", "").isalnum():
        raise ValueError("discovery_source must be a safe identifier.")
    return normalized


def normalize_discovery_url(value: str) -> str:
    """Normalize identity-relevant URL parts without rewriting content paths."""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except (AttributeError, ValueError) as error:
        raise ValueError("source_url must be a valid HTTP(S) URL.") from error
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be a valid HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise ValueError("source_url must not contain credentials.")

    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{port}" if port is not None else hostname
    query = []
    for name, item in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = name.casefold()
        if lowered.startswith("utm_") or lowered in TRACKING_PARAMETERS:
            continue
        query.append((name, "REDACTED" if is_sensitive_name(name) else item))
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path, urlencode(query, doseq=True), "")
    )


def candidate_id(discovery_source: str, source_url: str) -> str:
    source = _source_name(discovery_source)
    normalized_url = normalize_discovery_url(source_url)
    digest = sha256(f"{source}\0{normalized_url}".encode("utf-8")).hexdigest()
    return f"candidate_{digest}"


def build_candidate(
    *,
    discovered_at: str,
    discovery_source: str,
    source_url: str,
    advertiser_brand_text: str,
    product_text: str | None = None,
    campaign_text: str | None = None,
    artist_model_text: str | None = None,
    publication_date: str | None = None,
    market_code: str = "KR",
    discovered_for_artist_id: str | None = None,
    discovery_signal: str | None = None,
) -> dict[str, Any]:
    if market_code != "KR":
        raise ValueError("Advertising discovery market_code must be KR.")
    if not isinstance(advertiser_brand_text, str) or not advertiser_brand_text.strip():
        raise ValueError("advertiser_brand_text is required.")
    if publication_date is not None:
        try:
            publication_date = date.fromisoformat(publication_date).isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("publication_date must be an ISO date.") from error
    source = _source_name(discovery_source)
    normalized_url = normalize_discovery_url(source_url)
    return {
        "candidate_id": candidate_id(source, normalized_url),
        "discovered_for_artist_id": discovered_for_artist_id,
        "discovery_signal": discovery_signal,
        "discovered_at": _utc_timestamp(discovered_at),
        "discovery_source": source,
        "source_url": normalized_url,
        "advertiser_brand_text": advertiser_brand_text.strip(),
        "product_text": product_text,
        "campaign_text": campaign_text,
        "artist_model_text": artist_model_text,
        "publication_date": publication_date,
        "market_code": "KR",
        "evidence_status": EvidenceStatus.DISCOVERED.value,
        "official_source_url": None,
        "rejection_reason": None,
    }


def transition_candidate(
    candidate: dict[str, Any],
    new_status: EvidenceStatus | str,
    *,
    official_source_url: str | None = None,
    rejection_reason: str | None = None,
    official_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = EvidenceStatus(candidate["evidence_status"])
    target = EvidenceStatus(new_status)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid evidence transition: {current.value} -> {target.value}.")
    updated = dict(candidate)
    updated["evidence_status"] = target.value
    if official_evidence is not None:
        if official_evidence.get("candidate_id") != candidate.get("candidate_id"):
            raise ValueError("Official evidence must reference the candidate.")
        required_evidence_status = (
            EvidenceStatus.VERIFIED.value
            if target == EvidenceStatus.VERIFIED
            else EvidenceStatus.OFFICIAL_SOURCE_FOUND.value
        )
        if official_evidence.get("verification_status") != required_evidence_status:
            raise ValueError(
                f"Official evidence must have {required_evidence_status} status."
            )
        evidence_url = official_evidence.get("official_source_url")
        if official_source_url is not None and normalize_discovery_url(
            official_source_url
        ) != evidence_url:
            raise ValueError("Official evidence URL does not match official_source_url.")
        official_source_url = evidence_url
    if official_source_url is not None:
        updated["official_source_url"] = normalize_discovery_url(official_source_url)
    if target == EvidenceStatus.OFFICIAL_SOURCE_FOUND and official_evidence is None:
        raise ValueError("OFFICIAL_SOURCE_FOUND requires official evidence.")
    if target == EvidenceStatus.VERIFIED and official_evidence is None:
        raise ValueError("VERIFIED requires official evidence.")
    if target == EvidenceStatus.REJECTED:
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            raise ValueError("REJECTED requires rejection_reason.")
        updated["rejection_reason"] = rejection_reason.strip()
    return updated


def deduplicate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first occurrence of each deterministic candidate identity."""
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        expected = candidate_id(candidate["discovery_source"], candidate["source_url"])
        if candidate.get("candidate_id") != expected:
            raise ValueError("Candidate identity does not match its source URL.")
        if candidate.get("market_code") != "KR":
            raise ValueError("Advertising discovery market_code must be KR.")
        EvidenceStatus(candidate["evidence_status"])
        unique.setdefault(expected, candidate)
    return list(unique.values())
