"""Reusable contracts and source adapters for official advertising evidence."""

import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any, Protocol

if __package__:
    from .advertising_discovery import normalize_discovery_url
    from .advertising_domain import source_evidence_id
else:
    from advertising_discovery import normalize_discovery_url
    from advertising_domain import source_evidence_id


SUPPORTED_RELATIONSHIP_TYPES = {
    "MODEL",
    "AMBASSADOR",
    "ENDORSEMENT",
    "SPONSORED_CONTENT",
    "COLLABORATION",
    "EVENT_PARTNERSHIP",
}
EXTRACTION_VERSION = "official-advertising-evidence/1.0"


@dataclass(frozen=True)
class OfficialAdvertisingEvidence:
    source_name: str
    source_type: str
    source_url: str
    source_record_id: str | None
    observed_at: str
    published_at: str | None
    organization_name: str | None
    brand_name: str | None
    product_name: str | None
    campaign_name: str | None
    artist_name: str | None
    artist_entity_scope: str | None
    relationship_source_text: str | None
    relationship_type: str | None
    relationship_start_date: str | None
    relationship_end_date: str | None
    campaign_start_date: str | None
    campaign_end_date: str | None
    market_code: str | None
    creative_url: str | None
    content_hash: str
    extraction_version: str = EXTRACTION_VERSION

    @property
    def evidence_id(self) -> str:
        record_id = self.source_record_id or self.source_url
        return source_evidence_id(self.source_name, record_id, self.content_hash)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class OfficialEvidenceAdapter(Protocol):
    def parse(self, content: str, *, observed_at: str) -> OfficialAdvertisingEvidence:
        """Extract factual evidence from one already-acquired official document."""


def _plain_text(content: str) -> str:
    return " ".join(html.unescape(re.sub(r"(?s)<[^>]+>", " ", content)).split())


def _utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError("observed_at must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_date(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an ISO date.") from error


def normalize_relationship(source_text: str | None) -> str | None:
    """Normalize only explicit commercial-role wording."""
    if not source_text:
        return None
    text = " ".join(source_text.casefold().split())
    if re.search(
        r"(?:전속\s*모델|브랜드\s*모델|광고\s*모델|모델로.{0,40}발탁)", text
    ):
        return "MODEL"
    if re.search(r"(?:앰배서더|앰버서더|\bambassador\b)", text):
        return "AMBASSADOR"
    if re.search(r"(?:공식\s*후원|스폰서드\s*콘텐츠|\bsponsored content\b)", text):
        return "SPONSORED_CONTENT"
    if re.search(r"(?:브랜드와\s*공식\s*협업|브랜드\s*컬래버레이션|공식\s*콜라보레이션)", text):
        return "COLLABORATION"
    if re.search(r"(?:공식\s*추천|\bendorsement\b)", text):
        return "ENDORSEMENT"
    if re.search(r"(?:공식\s*행사\s*파트너|\bevent partnership\b)", text):
        return "EVENT_PARTNERSHIP"
    return None


def factual_content_hash(values: dict[str, Any]) -> str:
    """Hash stable factual inputs, excluding credentials and page chrome."""
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def validate_official_evidence(evidence: OfficialAdvertisingEvidence) -> None:
    if not evidence.source_name.strip() or not evidence.source_type.strip():
        raise ValueError("source_name and source_type are required.")
    normalize_discovery_url(evidence.source_url)
    if not evidence.source_record_id and not evidence.source_url:
        raise ValueError("A source record ID or stable source URL is required.")
    _utc_timestamp(evidence.observed_at)
    for field_name in (
        "published_at", "relationship_start_date", "relationship_end_date",
        "campaign_start_date", "campaign_end_date",
    ):
        _optional_date(getattr(evidence, field_name), field_name)
    if evidence.artist_name and not evidence.artist_name.strip():
        raise ValueError("artist_name must contain source text.")
    if evidence.relationship_type is not None:
        if evidence.relationship_type not in SUPPORTED_RELATIONSHIP_TYPES:
            raise ValueError("Unsupported relationship_type.")
        if normalize_relationship(evidence.relationship_source_text) != evidence.relationship_type:
            raise ValueError("Normalized relationship lacks supporting source wording.")
        if not evidence.artist_name:
            raise ValueError("Artist-linked relationship evidence requires artist source text.")
    for start_name, end_name in (
        ("relationship_start_date", "relationship_end_date"),
        ("campaign_start_date", "campaign_end_date"),
    ):
        start, end = getattr(evidence, start_name), getattr(evidence, end_name)
        if start and end and date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError(f"{start_name} must not be after {end_name}.")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.content_hash):
        raise ValueError("content_hash must be a SHA-256 hex digest.")


def minimal_bronze_evidence(evidence: OfficialAdvertisingEvidence) -> dict[str, Any]:
    """Prepare minimal factual provenance; this function performs no write."""
    validate_official_evidence(evidence)
    return {
        "storage_mode": "MINIMAL_FACTUAL",
        "source_name": evidence.source_name,
        "source_type": evidence.source_type,
        "source_url": normalize_discovery_url(evidence.source_url),
        "source_record_id": evidence.source_record_id,
        "observed_at": evidence.observed_at,
        "published_at": evidence.published_at,
        "content_hash": evidence.content_hash,
        "extraction_version": evidence.extraction_version,
        "evidence": evidence.as_dict(),
    }


def minimal_bronze_object_name(evidence: OfficialAdvertisingEvidence) -> str:
    validate_official_evidence(evidence)
    source = re.sub(r"[^a-z0-9_-]+", "-", evidence.source_name.casefold()).strip("-")
    record = evidence.source_record_id or sha256(evidence.source_url.encode()).hexdigest()
    record = re.sub(r"[^A-Za-z0-9._=-]+", "-", record)
    return (
        f"bronze/advertising/official_brand/source={source}/"
        f"source_record_id={record}/content_hash={evidence.content_hash}/evidence.json"
    )


def canonical_mapping_plan(evidence: OfficialAdvertisingEvidence) -> dict[str, Any]:
    """Describe supported canonical writes without resolving or persisting entities."""
    validate_official_evidence(evidence)
    campaign_supported = bool(
        evidence.campaign_name or (evidence.brand_name and evidence.relationship_type)
    )
    return {
        "advertiser_organization": evidence.organization_name,
        "brand": evidence.brand_name,
        "product": evidence.product_name,
        "advertising_campaign": evidence.campaign_name if campaign_supported else None,
        "campaign_artist": (
            {
                "artist_source_name": evidence.artist_name,
                "artist_entity_scope": evidence.artist_entity_scope,
                "participation_role": evidence.relationship_type,
            }
            if campaign_supported and evidence.artist_name and evidence.relationship_type
            else None
        ),
        "campaign_product": (
            evidence.product_name if campaign_supported and evidence.product_name else None
        ),
        "campaign_market": evidence.market_code if campaign_supported else None,
        "advertisement_creative": evidence.creative_url,
        "source_evidence": evidence.evidence_id,
        "canonical_field_evidence": [
            field
            for field, value in (
                ("organization_name", evidence.organization_name),
                ("brand_name", evidence.brand_name),
                ("product_name", evidence.product_name),
                ("campaign_name", evidence.campaign_name),
                ("participation_role", evidence.relationship_type),
                ("relationship_start_date", evidence.relationship_start_date),
                ("relationship_end_date", evidence.relationship_end_date),
                ("campaign_start_date", evidence.campaign_start_date),
                ("campaign_end_date", evidence.campaign_end_date),
            )
            if value is not None
        ],
    }


class DongAOtsukaNewsAdapter:
    source_url = "https://www.donga-otsuka.co.kr/customer/board/board_content.asp?idx=672&t_name=BOARD13"
    source_record_id = "idx=672"

    def parse(self, content: str, *, observed_at: str) -> OfficialAdvertisingEvidence:
        text = _plain_text(content)
        match = re.search(
            r"(나랑드사이다\s*모델로\s*걸그룹\s*리센느\s*\(RESCENE\)를\s*발탁)", text
        )
        relationship_text = match.group(1) if match else None
        facts = {
            "organization_name": "Dong-A Otsuka" if "동아오츠카" in text else None,
            "brand_name": "Narangd Cider" if "나랑드사이다" in text else None,
            "artist_name": "RESCENE" if re.search(r"리센느\s*\(RESCENE\)", text) else None,
            "relationship_source_text": relationship_text,
        }
        evidence = OfficialAdvertisingEvidence(
            source_name="Dong-A Otsuka",
            source_type="OFFICIAL_COMPANY_NEWS",
            source_url=self.source_url,
            source_record_id=self.source_record_id,
            observed_at=_utc_timestamp(observed_at),
            published_at="2026-08-27",
            organization_name=facts["organization_name"],
            brand_name=facts["brand_name"],
            product_name=None,
            campaign_name=None,
            artist_name=facts["artist_name"],
            artist_entity_scope="GROUP" if facts["artist_name"] else None,
            relationship_source_text=relationship_text,
            relationship_type=normalize_relationship(relationship_text),
            relationship_start_date=None,
            relationship_end_date=None,
            campaign_start_date=None,
            campaign_end_date=None,
            market_code=None,
            creative_url=None,
            content_hash=factual_content_hash(facts),
        )
        validate_official_evidence(evidence)
        return evidence


class DominoNewsAdapter:
    source_url = "https://web.dominos.co.kr/bbs/newsView?idx=3230"
    source_record_id = "idx=3230"

    def parse(self, content: str, *, observed_at: str) -> OfficialAdvertisingEvidence:
        text = _plain_text(content)
        match = re.search(
            r"(리센느\s*\(RESCENE\)를\s*(?:새로운\s*)?브랜드\s*전속\s*모델로\s*발탁)", text
        )
        relationship_text = match.group(1) if match else None
        facts = {
            "brand_name": "Domino's Pizza" if "도미노피자" in text else None,
            "artist_name": "RESCENE" if re.search(r"리센느\s*\(RESCENE\)", text) else None,
            "relationship_source_text": relationship_text,
            "campaign_name": "2026 summer TV commercial" if "TVCF" in text else None,
        }
        evidence = OfficialAdvertisingEvidence(
            source_name="Domino's Korea",
            source_type="OFFICIAL_BRAND_NEWS",
            source_url=self.source_url,
            source_record_id=self.source_record_id,
            observed_at=_utc_timestamp(observed_at),
            published_at="2026-07-13",
            organization_name=None,
            brand_name=facts["brand_name"],
            product_name=None,
            campaign_name=facts["campaign_name"],
            artist_name=facts["artist_name"],
            artist_entity_scope="GROUP" if facts["artist_name"] else None,
            relationship_source_text=relationship_text,
            relationship_type=normalize_relationship(relationship_text),
            relationship_start_date=None,
            relationship_end_date=None,
            campaign_start_date=None,
            campaign_end_date=None,
            market_code=None,
            creative_url=None,
            content_hash=factual_content_hash(facts),
        )
        validate_official_evidence(evidence)
        return evidence
