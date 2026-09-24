"""Shared canonical transform for normalized official advertising evidence."""

from dataclasses import dataclass, field
from typing import Any

if __package__:
    from .advertising_domain import DataQualityIssue, QualitySeverity
    from .advertising_official_ingestion import (
        OfficialAdvertisingEvidence,
        validate_official_evidence,
    )
    from .advertising_silver import (
        AdvertisingSilverResult,
        _stable_id,
        brand_id,
        campaign_id,
        organization_id,
        product_id,
    )
    from .mvp_config import RESCENE_ARTIST_ID
else:
    from advertising_domain import DataQualityIssue, QualitySeverity
    from advertising_official_ingestion import (
        OfficialAdvertisingEvidence,
        validate_official_evidence,
    )
    from advertising_silver import (
        AdvertisingSilverResult,
        _stable_id,
        brand_id,
        campaign_id,
        organization_id,
        product_id,
    )
    from mvp_config import RESCENE_ARTIST_ID


def _key(value: str) -> str:
    return " ".join(value.casefold().split())


ARTIST_ALIASES = {
    _key("RESCENE"): RESCENE_ARTIST_ID,
    _key("리센느"): RESCENE_ARTIST_ID,
}
BRAND_ALIASES = {
    _key("Narangd Cider"): "Narangd Cider",
    _key("나랑드사이다"): "Narangd Cider",
    _key("Domino's Pizza"): "Domino's Pizza",
    _key("Domino’s Pizza"): "Domino's Pizza",
    _key("도미노피자"): "Domino's Pizza",
}
ORGANIZATION_ALIASES = {
    _key("Dong-A Otsuka"): "Dong-A Otsuka",
    _key("동아오츠카"): "Dong-A Otsuka",
}
# Products require an explicit governed mapping. No current fixture establishes one.
PRODUCT_ALIASES: dict[tuple[str, str], str] = {}


@dataclass
class OfficialSilverTransformResult:
    silver: AdvertisingSilverResult
    quality_issues: list[DataQualityIssue] = field(default_factory=list)


def _field_evidence(
    evidence: OfficialAdvertisingEvidence,
    entity_type: str,
    entity_id: str,
    field_name: str,
    asserted_value: str,
    *,
    selection_reason: str = "Deterministic explicit alias resolution.",
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "field_name": field_name,
        "source_evidence_id": evidence.evidence_id,
        "asserted_value": asserted_value,
        "is_selected": True,
        "selection_reason": selection_reason,
        "observed_at": evidence.observed_at,
    }


def transform_official_evidence(
    evidence: OfficialAdvertisingEvidence,
    *,
    bronze_reference: str,
) -> OfficialSilverTransformResult:
    """Resolve one source-independent evidence contract into existing Silver rows."""
    validate_official_evidence(evidence)
    result = AdvertisingSilverResult()
    issues: list[DataQualityIssue] = []
    result.source_evidence.append({
        "source_evidence_id": evidence.evidence_id,
        "source_name": evidence.source_name,
        "source_type": evidence.source_type,
        "source_url": evidence.source_url,
        "source_record_id": evidence.source_record_id,
        "collected_at": evidence.observed_at,
        "published_at": f"{evidence.published_at}T00:00:00Z" if evidence.published_at else None,
        "content_hash": evidence.content_hash,
        "authority_level": "OFFICIAL",
        "raw_bronze_reference": bronze_reference,
        "verification_status": "VERIFIED",
    })

    artist = ARTIST_ALIASES.get(_key(evidence.artist_name)) if evidence.artist_name else None
    if evidence.artist_name and artist is None:
        issues.append(DataQualityIssue(
            QualitySeverity.UNRESOLVED, "unknown_artist", evidence.evidence_id,
            f"No explicit artist alias for {evidence.artist_name!r}.",
        ))
    if artist:
        result.canonical_field_evidence.append(_field_evidence(
            evidence, "ARTIST", artist, "artist_id", evidence.artist_name
        ))

    organization = None
    if evidence.organization_name:
        canonical_name = ORGANIZATION_ALIASES.get(_key(evidence.organization_name))
        if canonical_name:
            organization = organization_id(canonical_name)
            result.organizations.append({
                "organization_id": organization,
                "organization_name": canonical_name,
            })
            result.canonical_field_evidence.append(_field_evidence(
                evidence, "ADVERTISER_ORGANIZATION", organization,
                "organization_name", evidence.organization_name,
            ))
        else:
            issues.append(DataQualityIssue(
                QualitySeverity.UNRESOLVED, "unknown_organization", evidence.evidence_id,
                f"No explicit organization alias for {evidence.organization_name!r}.",
            ))

    brand = None
    canonical_brand_name = None
    if evidence.brand_name:
        canonical_brand_name = BRAND_ALIASES.get(_key(evidence.brand_name))
        if canonical_brand_name:
            brand = brand_id(canonical_brand_name)
            result.brands.append({
                "brand_id": brand,
                "brand_name": canonical_brand_name,
                "organization_id": organization,
            })
            result.canonical_field_evidence.append(_field_evidence(
                evidence, "BRAND", brand, "brand_name", evidence.brand_name
            ))
        else:
            issues.append(DataQualityIssue(
                QualitySeverity.UNRESOLVED, "unknown_brand", evidence.evidence_id,
                f"No explicit brand alias for {evidence.brand_name!r}.",
            ))

    product = None
    if evidence.product_name:
        resolved_product = (
            PRODUCT_ALIASES.get((_key(canonical_brand_name), _key(evidence.product_name)))
            if canonical_brand_name else None
        )
        if resolved_product and brand:
            product = product_id(brand, resolved_product)
            result.products.append({
                "product_id": product,
                "brand_id": brand,
                "product_name": resolved_product,
                "source_category_text": None,
            })
            result.canonical_field_evidence.append(_field_evidence(
                evidence, "PRODUCT", product, "product_name", evidence.product_name
            ))
        else:
            issues.append(DataQualityIssue(
                QualitySeverity.UNRESOLVED, "unresolved_product", evidence.evidence_id,
                f"Product {evidence.product_name!r} has no explicit canonical mapping.",
            ))
    else:
        issues.append(DataQualityIssue(
            QualitySeverity.UNRESOLVED, "unresolved_product", evidence.evidence_id,
            "Official evidence does not establish a canonical product.",
        ))

    campaign = None
    legacy_narangd = (
        canonical_brand_name == "Narangd Cider"
        and evidence.source_record_id == "idx=672"
        and artist == RESCENE_ARTIST_ID
        and evidence.relationship_type == "MODEL"
    )
    if legacy_narangd:
        campaign = campaign_id(brand, "MODEL", artist)
    elif brand and evidence.campaign_name:
        campaign = _stable_id("campaign", f"{brand}:named:{evidence.campaign_name}")
    if campaign:
        result.campaigns.append({
            "campaign_id": campaign,
            "campaign_name": evidence.campaign_name,
            "relationship_type": "MODEL" if legacy_narangd else None,
            "announced_at": None,
            "campaign_start_date": evidence.campaign_start_date,
            "campaign_end_date": evidence.campaign_end_date,
            "status": None,
        })
        if brand:
            result.campaign_brands.append({
                "campaign_id": campaign,
                "brand_id": brand,
            })
            result.canonical_field_evidence.append(_field_evidence(
                evidence, "CAMPAIGN", campaign, "brand_id", brand,
                selection_reason="Brand explicitly asserted by the official source.",
            ))
        if evidence.campaign_name:
            result.canonical_field_evidence.append(_field_evidence(
                evidence, "CAMPAIGN", campaign, "campaign_name", evidence.campaign_name
            ))
    elif evidence.brand_name or evidence.artist_name:
        issues.append(DataQualityIssue(
            QualitySeverity.UNRESOLVED, "insufficient_campaign_context",
            evidence.evidence_id, "Evidence is insufficient for deterministic campaign identity.",
        ))

    if campaign and artist and evidence.relationship_type:
        relationship = _stable_id("campaign_artist", f"{campaign}:{artist}")
        result.campaign_artists.append({
            "campaign_artist_id": relationship,
            "campaign_id": campaign,
            "artist_id": artist,
            "participation_role": evidence.relationship_type,
        })
        result.canonical_field_evidence.append(_field_evidence(
            evidence, "CAMPAIGN_ARTIST", relationship, "participation_role",
            evidence.relationship_type,
            selection_reason=(
                "Explicit official source wording: "
                f"{evidence.relationship_source_text}"
            ),
        ))

    if campaign and product:
        result.campaign_products.append({
            "campaign_product_id": _stable_id("campaign_product", f"{campaign}:{product}"),
            "campaign_id": campaign,
            "product_id": product,
        })

    if evidence.market_code is None:
        issues.append(DataQualityIssue(
            QualitySeverity.UNRESOLVED, "unresolved_market", evidence.evidence_id,
            "Official evidence does not establish a governed market.",
        ))
    if evidence.published_at and not evidence.relationship_start_date:
        issues.append(DataQualityIssue(
            QualitySeverity.WARNING, "publication_without_effective_date",
            evidence.evidence_id,
            "Publication date is known but relationship start date remains unknown.",
        ))
    if brand and organization is None:
        issues.append(DataQualityIssue(
            QualitySeverity.WARNING, "organization_unresolved", brand,
            "Brand resolved while organization remains unresolved.",
        ))
    return OfficialSilverTransformResult(result, issues)


def project_gold_artist_commercial_intelligence(
    result: AdvertisingSilverResult,
) -> list[dict[str, Any]]:
    """Project valid relationships at artist × campaign × product × market grain."""
    products_by_campaign: dict[str, list[str | None]] = {}
    for row in result.campaign_products:
        products_by_campaign.setdefault(row["campaign_id"], []).append(row["product_id"])
    markets_by_campaign: dict[str, list[str | None]] = {}
    for row in result.campaign_markets:
        markets_by_campaign.setdefault(row["campaign_id"], []).append(row["market_id"])
    market_codes = {row["market_id"]: row["market_code"] for row in result.markets}
    evidence_ids = {row["source_evidence_id"] for row in result.source_evidence}
    brands_by_campaign: dict[str, list[str]] = {}
    for row in result.campaign_brands:
        brands_by_campaign.setdefault(row["campaign_id"], []).append(row["brand_id"])
    campaigns = {row["campaign_id"]: row for row in result.campaigns}
    rows = []
    for relationship in result.campaign_artists:
        campaign = campaigns[relationship["campaign_id"]]
        products = products_by_campaign.get(campaign["campaign_id"], [None])
        markets = markets_by_campaign.get(campaign["campaign_id"], [None])
        brands = brands_by_campaign.get(campaign["campaign_id"], [None])
        for brand in brands:
            for product in products:
                for market in markets:
                    rows.append({
                        "artist_id": relationship["artist_id"],
                        "campaign_id": campaign["campaign_id"],
                        "relationship_type": relationship["participation_role"],
                        "brand_id": brand,
                        "product_id": product,
                        "market_code": market_codes.get(market) if market else None,
                        "has_official_evidence": bool(evidence_ids),
                        "unresolved_flag": any(
                            value is None for value in (brand, product, market)
                        ),
                    })
    return rows
