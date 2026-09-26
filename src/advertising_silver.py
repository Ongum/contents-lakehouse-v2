"""Transform persisted advertising Bronze evidence into canonical Silver records."""

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

if __package__:
    from .advertising_official_ingestion import DongAOtsukaNewsAdapter
    from .mvp_config import RESCENE_ARTIST_ID
else:
    from advertising_official_ingestion import DongAOtsukaNewsAdapter
    from mvp_config import RESCENE_ARTIST_ID


ADVERTISING_PREFIX = "bronze/advertising/"
NARANGD_SOURCE_IDENTIFIER = "donga-otsuka:news:672"
RELATIONSHIP_TYPES = {
    "MODEL",
    "AMBASSADOR",
    "ENDORSEMENT",
    "SPONSORED_CONTENT",
    "COLLABORATION",
    "EVENT_PARTNERSHIP",
}


@dataclass
class AdvertisingSilverResult:
    organizations: list[dict[str, Any]] = field(default_factory=list)
    brands: list[dict[str, Any]] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    product_categories: list[dict[str, Any]] = field(default_factory=list)
    product_category_assignments: list[dict[str, Any]] = field(default_factory=list)
    product_tags: list[dict[str, Any]] = field(default_factory=list)
    product_tag_assignments: list[dict[str, Any]] = field(default_factory=list)
    source_evidence: list[dict[str, Any]] = field(default_factory=list)
    campaigns: list[dict[str, Any]] = field(default_factory=list)
    campaign_brands: list[dict[str, Any]] = field(default_factory=list)
    advertisement_creatives: list[dict[str, Any]] = field(default_factory=list)
    creative_tags: list[dict[str, Any]] = field(default_factory=list)
    creative_tag_assignments: list[dict[str, Any]] = field(default_factory=list)
    canonical_field_evidence: list[dict[str, Any]] = field(default_factory=list)
    campaign_artists: list[dict[str, Any]] = field(default_factory=list)
    campaign_products: list[dict[str, Any]] = field(default_factory=list)
    campaign_sources: list[dict[str, Any]] = field(default_factory=list)
    markets: list[dict[str, Any]] = field(default_factory=list)
    campaign_markets: list[dict[str, Any]] = field(default_factory=list)
    market_metrics: list[dict[str, Any]] = field(default_factory=list)
    invalid_records: list[dict[str, Any]] = field(default_factory=list)


class AdvertisingTransformError(ValueError):
    """Raised when advertising Bronze evidence cannot be transformed safely."""


def _stable_id(kind: str, identity: str) -> str:
    value = " ".join(identity.casefold().split())
    return f"{kind}_{uuid5(NAMESPACE_URL, f'contents-lakehouse:{kind}:{value}').hex}"


def organization_id(organization_name: str) -> str:
    return _stable_id("organization", organization_name)


def brand_id(brand_name: str) -> str:
    return _stable_id("brand", brand_name)


def product_id(parent_brand_id: str, product_name: str) -> str:
    return _stable_id("product", f"{parent_brand_id}:{product_name}")


def campaign_id(parent_brand_id: str, relationship_type: str, artist_id: str) -> str:
    if relationship_type not in RELATIONSHIP_TYPES:
        raise AdvertisingTransformError(
            f"Unsupported relationship_type: {relationship_type}."
        )
    return _stable_id(
        "campaign", f"{parent_brand_id}:{relationship_type}:{artist_id}"
    )


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdvertisingTransformError(f"Missing required {field_name}.")
    return value.strip()


def _utc_timestamp(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise AdvertisingTransformError(f"Invalid {field_name}.") from error
    if parsed.tzinfo is None:
        raise AdvertisingTransformError(f"Invalid {field_name}: timezone is required.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_date(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    text = _required_text(value, field_name)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise AdvertisingTransformError(f"Invalid {field_name}.") from error


def _plain_text(raw_content: str) -> str:
    without_tags = re.sub(r"(?s)<[^>]+>", " ", raw_content)
    return " ".join(html.unescape(without_tags).split())


def _invalid(source_reference: str, message: str) -> dict[str, str]:
    return {
        "pipeline_stage": "bronze_to_silver",
        "source_reference": source_reference,
        "error_type": "record_validation_error",
        "error_message": message,
    }


def transform_advertising_bronze(
    source_reference: str, envelope: dict[str, Any]
) -> AdvertisingSilverResult:
    result = AdvertisingSilverResult()
    try:
        if not isinstance(envelope, dict):
            raise AdvertisingTransformError("Bronze envelope must be an object.")
        if not source_reference.startswith(ADVERTISING_PREFIX):
            raise AdvertisingTransformError("Invalid advertising Bronze reference.")
        if envelope.get("source_type") != "official_company_page":
            raise AdvertisingTransformError("Unsupported advertising source_type.")
        if envelope.get("source_identifier") != NARANGD_SOURCE_IDENTIFIER:
            raise AdvertisingTransformError("Unsupported advertising source_identifier.")
        source_name = _required_text(envelope.get("source_name"), "source_name")
        source_url = _required_text(envelope.get("source_url"), "source_url")
        content_hash = _required_text(envelope.get("content_hash"), "content_hash")
        if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise AdvertisingTransformError("Invalid content_hash.")
        retrieved_at = _utc_timestamp(envelope.get("retrieved_at"), "retrieved_at")
        published_at = _optional_date(envelope.get("published_at"), "published_at")
        collector_version = _required_text(
            envelope.get("collector_version"), "collector_version"
        )
        raw_content = _required_text(envelope.get("raw_content"), "raw_content")
        text = _plain_text(raw_content)
    except AdvertisingTransformError as error:
        result.invalid_records.append(_invalid(source_reference, str(error)))
        return result

    try:
        official_evidence = DongAOtsukaNewsAdapter().parse(
            raw_content, observed_at=retrieved_at
        )
    except ValueError as error:
        result.invalid_records.append(_invalid(source_reference, str(error)))
        return result
    if official_evidence.relationship_type != "MODEL":
        result.invalid_records.append(
            _invalid(source_reference, "Missing explicit Narangd/RESCENE model evidence.")
        )
        return result

    if __package__:
        from .advertising_official_silver import transform_official_evidence
    else:
        from advertising_official_silver import transform_official_evidence
    canonical = transform_official_evidence(
        official_evidence, bronze_reference=source_reference
    )
    result = canonical.silver
    organization = (
        result.organizations[0]["organization_id"] if result.organizations else None
    )
    narangd_brand_id = result.brands[0]["brand_id"]
    model_campaign_id = result.campaigns[0]["campaign_id"]

    sales_match = re.search(
        r"나랑드사이다의\s*한\s*달간\s*매출이\s*전년\s*동기\s*대비\s*(\d+(?:\.\d+)?)%\s*증가",
        text,
    )
    category_match = re.search(
        r"(?:제품\s*카테고리|카테고리)\s*[:：]\s*([^.;]+)", text
    )
    source_category_text = category_match.group(1).strip() if category_match else None
    product = None
    if sales_match or source_category_text:
        product = product_id(narangd_brand_id, "Narangd Cider")
        result.products.append(
            {
                "product_id": product,
                "brand_id": narangd_brand_id,
                "product_name": "Narangd Cider",
                "source_category_text": source_category_text,
            }
        )
        result.campaign_products.append(
            {
                "campaign_product_id": _stable_id(
                    "campaign_product", f"{model_campaign_id}:{product}"
                ),
                "campaign_id": model_campaign_id,
                "product_id": product,
            }
        )
        # Source category text is evidence, not a normalized taxonomy assignment.
        # A governed taxonomy process may populate product_category and its bridge.

    result.campaign_sources.append(
        {
            "campaign_id": model_campaign_id,
            "source_type": envelope["source_type"],
            "source_name": source_name,
            "source_url": source_url,
            "source_identifier": envelope["source_identifier"],
            "bronze_object_reference": source_reference,
            "content_hash": content_hash,
            "retrieved_at": retrieved_at,
            "published_at": published_at,
            "collector_version": collector_version,
        }
    )

    if sales_match:
        result.market_metrics.append(
            {
                "metric_id": _stable_id(
                    "market_metric", f"{content_hash}:SALES_GROWTH"
                ),
                "campaign_id": model_campaign_id,
                "product_id": product,
                "market_id": None,
                "metric_type": "SALES_GROWTH",
                "value": float(sales_match.group(1)),
                "unit": "PERCENT",
                "measurement_start": None,
                "measurement_end": None,
                "measurement_period_precision": None,
                "observed_at": retrieved_at,
                "comparison_type": "YOY",
                "comparison_start": None,
                "comparison_end": None,
                "comparison_period_precision": None,
                "channel": "online, company mall, convenience stores",
                "scope": "one-month sales after model selection",
                "asset_reference": None,
                "reported_by": "Dong-A Otsuka",
                "is_company_reported": True,
                "source_reference": source_reference,
                "attribution_note": (
                    "Company-reported association after model selection; "
                    "no causal effect is inferred."
                ),
            }
        )

    views_match = re.search(
        r"관련\s*콘텐츠의\s*누적\s*조회수가\s*([\d,]+)만\s*회를\s*돌파",
        text,
    )
    if views_match:
        value = float(int(views_match.group(1).replace(",", "")) * 10_000)
        result.market_metrics.append(
            {
                "metric_id": _stable_id(
                    "market_metric", f"{content_hash}:CONTENT_VIEW_COUNT"
                ),
                "campaign_id": model_campaign_id,
                "product_id": product,
                "market_id": None,
                "metric_type": "CONTENT_VIEW_COUNT",
                "value": value,
                "unit": "VIEWS",
                "measurement_start": None,
                "measurement_end": None,
                "measurement_period_precision": None,
                "observed_at": retrieved_at,
                "comparison_type": None,
                "comparison_start": None,
                "comparison_end": None,
                "comparison_period_precision": None,
                "channel": "Dong-A Otsuka official YouTube",
                "scope": "cumulative Narangd Cider and RESCENE-related content views",
                "asset_reference": None,
                "reported_by": "Dong-A Otsuka",
                "is_company_reported": True,
                "source_reference": source_reference,
                "attribution_note": None,
            }
        )
    return result


def latest_narangd_bronze(storage: Any) -> tuple[str, dict[str, Any]]:
    if hasattr(storage, 'latest_source_record'):
        if __package__:
            from .advertising_sources import NARANGD_SOURCE
        else:
            from advertising_sources import NARANGD_SOURCE
        latest = storage.latest_source_record(NARANGD_SOURCE)
        if latest is None:
            raise AdvertisingTransformError('No persisted Narangd advertising Bronze object found.')
        return latest
    objects = storage.list_records(prefix=ADVERTISING_PREFIX)
    valid = [
        item
        for item in objects
        if isinstance(item[1], dict)
        and item[1].get("source_identifier") == NARANGD_SOURCE_IDENTIFIER
        and isinstance(item[1].get("retrieved_at"), str)
    ]
    if not valid:
        raise AdvertisingTransformError("No persisted Narangd advertising Bronze object found.")
    return max(valid, key=lambda item: item[1]["retrieved_at"])


def transform_latest_from_minio(storage: Any) -> AdvertisingSilverResult:
    source_reference, envelope = latest_narangd_bronze(storage)
    return transform_advertising_bronze(source_reference, envelope)
