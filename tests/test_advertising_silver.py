import unittest

from src.advertising_silver import (
    AdvertisingSilverResult,
    brand_id,
    campaign_id,
    organization_id,
    transform_advertising_bronze,
)
from src.advertising_silver_iceberg import (
    TABLE_DEFINITIONS,
    _merge_advertising,
    validate_advertising_silver_result,
)
from src.advertising_domain import (
    QualitySeverity,
    assess_advertising_quality,
    source_evidence_id,
)
from src.mvp_config import RESCENE_ARTIST_ID


SOURCE_REFERENCE = (
    "bronze/advertising/official_company_page/"
    "source_id=source/content_hash=hash/document.json"
)
ARTICLE = """
<html><body>
<div>동아오츠카(대표이사 사장 박철호)는 나랑드사이다 모델로 걸그룹
리센느(RESCENE)를 발탁한 이후 나랑드사이다의 한 달간 매출이 전년 동기
대비 48% 증가했다고 밝혔다.</div>
<div>매출은 7월 21일부터 8월 21일까지 한 달간의 판매 실적을 전년 동기와
비교한 수치다. 주요 온라인 채널과 동아오츠카 자사몰, 편의점 등의 판매
데이터를 기반으로 집계했다.</div>
<div>동아오츠카 공식 유튜브 채널에 게시된 나랑드사이다와 리센느 관련
콘텐츠의 누적 조회수가 1,800만 회를 돌파했다.</div>
</body></html>
"""


def envelope(raw_content=ARTICLE):
    return {
        "source_type": "official_company_page",
        "source_name": "Dong-A Otsuka Narangd Cider RESCENE sales update",
        "source_url": "https://example.test/news/672",
        "source_identifier": "donga-otsuka:news:672",
        "retrieved_at": "2026-09-23T09:47:02Z",
        "published_at": "2026-08-27",
        "content_hash": "a" * 64,
        "collector_version": "advertising-http/1.0",
        "raw_content": raw_content,
    }


class AdvertisingSilverTest(unittest.TestCase):
    def test_ids_are_deterministic_and_not_display_names(self):
        self.assertEqual(
            organization_id("Dong-A Otsuka"), organization_id("Dong-A Otsuka")
        )
        self.assertEqual(brand_id("Narangd Cider"), brand_id("Narangd Cider"))
        self.assertEqual(
            campaign_id(brand_id("Narangd Cider"), "MODEL", RESCENE_ARTIST_ID),
            campaign_id(brand_id("Narangd Cider"), "MODEL", RESCENE_ARTIST_ID),
        )
        self.assertNotEqual(organization_id("Dong-A Otsuka"), "Dong-A Otsuka")

    def test_builds_campaign_links_without_creating_artist(self):
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope())

        self.assertFalse(result.invalid_records)
        self.assertFalse(hasattr(result, "artists"))
        self.assertEqual(len(result.campaign_artists), 1)
        self.assertEqual(
            result.campaign_artists[0]["artist_id"], RESCENE_ARTIST_ID
        )
        self.assertEqual(result.campaign_artists[0]["participation_role"], "MODEL")

    def test_product_is_optional_and_no_category_taxonomy_is_invented(self):
        without_sales = (
            "나랑드사이다 모델로 걸그룹 리센느(RESCENE)를 발탁했다."
        )
        result = transform_advertising_bronze(
            SOURCE_REFERENCE, envelope(without_sales)
        )

        self.assertFalse(result.invalid_records)
        self.assertFalse(result.products)
        self.assertFalse(result.campaign_products)
        self.assertFalse(result.product_categories)

    def test_source_category_is_preserved_as_null_when_absent(self):
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope())

        self.assertEqual(result.products[0]["source_category_text"], None)
        self.assertFalse(result.product_categories)

    def test_source_category_text_does_not_create_normalized_taxonomy(self):
        content = ARTICLE + "<div>제품 카테고리: 제로칼로리 탄산음료.</div>"
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope(content))

        self.assertEqual(
            result.products[0]["source_category_text"], "제로칼로리 탄산음료"
        )
        self.assertFalse(result.product_categories)
        self.assertFalse(result.product_category_assignments)

    def test_publication_and_campaign_dates_remain_distinct(self):
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope())
        campaign = result.campaigns[0]
        source = result.campaign_sources[0]

        self.assertEqual(source["published_at"], "2026-08-27")
        self.assertIsNone(campaign["announced_at"])
        self.assertIsNone(campaign["campaign_start_date"])
        self.assertIsNone(campaign["campaign_end_date"])

    def test_lineage_references_exact_bronze_object(self):
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope())
        source = result.campaign_sources[0]

        self.assertEqual(source["bronze_object_reference"], SOURCE_REFERENCE)
        self.assertEqual(source["content_hash"], "a" * 64)
        self.assertEqual(source["collector_version"], "advertising-http/1.0")

    def test_rerun_is_deterministic(self):
        first = transform_advertising_bronze(SOURCE_REFERENCE, envelope())
        second = transform_advertising_bronze(SOURCE_REFERENCE, envelope())

        self.assertEqual(first, second)
        validate_advertising_silver_result(first)
        self.assertFalse(first.product_categories)
        self.assertFalse(first.product_tags)
        self.assertFalse(first.markets)
        self.assertFalse(first.campaign_markets)

    def test_only_explicit_metrics_are_created_without_causal_inference(self):
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope())
        metrics = {row["metric_type"]: row for row in result.market_metrics}

        self.assertEqual(metrics["SALES_GROWTH"]["value"], 48.0)
        self.assertEqual(metrics["SALES_GROWTH"]["unit"], "PERCENT")
        self.assertEqual(metrics["SALES_GROWTH"]["comparison_type"], "YOY")
        self.assertIsNone(metrics["SALES_GROWTH"]["measurement_start"])
        self.assertIsNone(metrics["SALES_GROWTH"]["market_id"])
        self.assertIsNone(metrics["SALES_GROWTH"]["measurement_period_precision"])
        self.assertIsNone(metrics["SALES_GROWTH"]["comparison_period_precision"])
        self.assertIn("no causal effect", metrics["SALES_GROWTH"]["attribution_note"])
        self.assertEqual(metrics["CONTENT_VIEW_COUNT"]["value"], 18_000_000.0)

    def test_metric_is_absent_when_not_explicit(self):
        content = "나랑드사이다 모델로 걸그룹 리센느(RESCENE)를 발탁했다."
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope(content))

        self.assertFalse(result.market_metrics)

    def test_ambiguous_or_malformed_input_is_reported(self):
        ambiguous = transform_advertising_bronze(
            SOURCE_REFERENCE, envelope("리센느와 나랑드사이다가 함께했다.")
        )
        malformed = transform_advertising_bronze(
            SOURCE_REFERENCE, {"source_type": "official_company_page"}
        )

        self.assertEqual(len(ambiguous.invalid_records), 1)
        self.assertFalse(ambiguous.campaigns)
        self.assertEqual(len(malformed.invalid_records), 1)

    def test_unsupported_relationship_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported relationship_type"):
            campaign_id("brand", "CELEBRITY", RESCENE_ARTIST_ID)

    def test_extended_tables_and_nullable_artist_relationship_are_defined(self):
        for table in (
            "product_category_assignment",
            "product_tag",
            "product_tag_assignment",
            "market",
            "campaign_market",
            "advertisement_creative",
            "source_evidence",
            "canonical_field_evidence",
            "campaign_brand",
            "creative_tag",
            "creative_tag_assignment",
        ):
            self.assertIn(table, TABLE_DEFINITIONS)
        self.assertIn("parent_category_id STRING", TABLE_DEFINITIONS["product_category"])
        self.assertIn("market_id STRING", TABLE_DEFINITIONS["campaign_market_metric"])
        self.assertNotIn(
            "relationship_type STRING NOT NULL",
            TABLE_DEFINITIONS["advertising_campaign"],
        )
        self.assertIn("tag_type STRING", TABLE_DEFINITIONS["product_tag"])
        self.assertIn(
            "source_evidence_id STRING",
            TABLE_DEFINITIONS["product_tag_assignment"],
        )

    def test_campaign_without_artist_is_valid(self):
        result = AdvertisingSilverResult(
            campaigns=[{
                "campaign_id": "campaign-no-artist",
                "campaign_name": None,
                "relationship_type": None,
                "announced_at": None,
                "campaign_start_date": None,
                "campaign_end_date": None,
                "status": None,
            }]
        )

        validate_advertising_silver_result(result)

    def test_campaign_brand_validates_duplicates_and_foreign_references(self):
        base = {
            "campaign_id": "campaign",
            "campaign_name": None,
            "relationship_type": None,
            "announced_at": None,
            "campaign_start_date": None,
            "campaign_end_date": None,
            "status": None,
        }
        brand = {
            "brand_id": "brand",
            "brand_name": "Brand",
            "organization_id": None,
        }
        valid = AdvertisingSilverResult(
            brands=[brand], campaigns=[base],
            campaign_brands=[{"campaign_id": "campaign", "brand_id": "brand"}],
        )
        validate_advertising_silver_result(valid)

        duplicate = AdvertisingSilverResult(
            brands=[brand], campaigns=[base],
            campaign_brands=[
                {"campaign_id": "campaign", "brand_id": "brand"},
                {"campaign_id": "campaign", "brand_id": "brand"},
            ],
        )
        with self.assertRaisesRegex(ValueError, "Duplicate campaign_brand"):
            validate_advertising_silver_result(duplicate)

        missing_campaign = AdvertisingSilverResult(
            brands=[brand],
            campaign_brands=[{"campaign_id": "missing", "brand_id": "brand"}],
        )
        with self.assertRaisesRegex(ValueError, "Unknown campaign_id"):
            validate_advertising_silver_result(missing_campaign)

        missing_brand = AdvertisingSilverResult(
            campaigns=[base],
            campaign_brands=[{"campaign_id": "campaign", "brand_id": "missing"}],
        )
        with self.assertRaisesRegex(ValueError, "Unknown brand_id"):
            validate_advertising_silver_result(missing_brand)

    def test_validation_rejects_bad_parents_duplicate_assignments_and_dates(self):
        category_result = AdvertisingSilverResult(
            product_categories=[{
                "category_id": "child",
                "category_name": "Child",
                "parent_category_id": "missing",
                "taxonomy_name": "products",
                "taxonomy_version": "1",
                "source_category_text": None,
            }]
        )
        with self.assertRaisesRegex(ValueError, "category parent"):
            validate_advertising_silver_result(category_result)

        market_result = AdvertisingSilverResult(markets=[
            {
                "market_id": "a",
                "market_code": "A",
                "market_name": "A",
                "market_type": "REGION",
                "parent_market_id": "b",
            },
            {
                "market_id": "b",
                "market_code": "B",
                "market_name": "B",
                "market_type": "REGION",
                "parent_market_id": "a",
            },
        ])
        with self.assertRaisesRegex(ValueError, "Cyclic market parent"):
            validate_advertising_silver_result(market_result)

        assignment_result = AdvertisingSilverResult(
            products=[{
                "product_id": "product",
                "brand_id": "brand",
                "product_name": "Product",
                "source_category_text": None,
            }],
            brands=[{
                "brand_id": "brand",
                "brand_name": "Brand",
                "organization_id": None,
            }],
            product_tags=[{"tag_id": "tag", "tag_name": "TAG"}],
            product_tag_assignments=[
                {"product_id": "product", "tag_id": "tag"},
                {"product_id": "product", "tag_id": "tag"},
            ],
        )
        with self.assertRaisesRegex(ValueError, "Duplicate product_tag_assignment"):
            validate_advertising_silver_result(assignment_result)

        date_result = AdvertisingSilverResult(campaigns=[{
            "campaign_id": "campaign",
            "campaign_name": None,
            "relationship_type": None,
            "announced_at": None,
            "campaign_start_date": "2026-02-02",
            "campaign_end_date": "2026-02-01",
            "status": None,
        }])
        with self.assertRaisesRegex(ValueError, "campaign_start_date"):
            validate_advertising_silver_result(date_result)

    def test_validation_rejects_unknown_foreign_key_style_reference(self):
        result = AdvertisingSilverResult(
            campaigns=[{
                "campaign_id": "campaign",
                "campaign_name": None,
                "relationship_type": None,
                "announced_at": None,
                "campaign_start_date": None,
                "campaign_end_date": None,
                "status": None,
            }],
            campaign_markets=[{"campaign_id": "campaign", "market_id": "missing"}],
        )
        with self.assertRaisesRegex(ValueError, "Unknown market_id"):
            validate_advertising_silver_result(result)

    def test_creative_date_role_and_evidence_references_are_validated(self):
        result = AdvertisingSilverResult(
            campaigns=[{
                "campaign_id": "campaign",
                "campaign_name": None,
                "relationship_type": None,
                "announced_at": None,
                "campaign_start_date": None,
                "campaign_end_date": None,
                "status": None,
            }],
            campaign_artists=[{
                "campaign_artist_id": "relationship",
                "campaign_id": "campaign",
                "artist_id": RESCENE_ARTIST_ID,
                "participation_role": "UNSUPPORTED",
            }],
        )
        with self.assertRaisesRegex(ValueError, "Unsupported participation_role"):
            validate_advertising_silver_result(result)

        result.campaign_artists = []
        result.advertisement_creatives = [{
            "creative_id": "creative",
            "campaign_id": "campaign",
            "brand_id": None,
            "product_id": None,
            "source_type": "STRUCTURED_PUBLIC_SOURCE",
            "source_creative_id": "native-1",
            "creative_type": "VIDEO",
            "title": None,
            "description": None,
            "media_url": None,
            "landing_url": None,
            "platform": None,
            "first_observed_at": "2026-09-25T00:00:00Z",
            "last_observed_at": "2026-09-24T00:00:00Z",
            "published_at": None,
            "active_from": None,
            "active_to": None,
            "source_evidence_id": "missing",
        }]
        with self.assertRaisesRegex(ValueError, "source_evidence_id"):
            validate_advertising_silver_result(result)

    def test_quality_findings_are_explainable_and_non_mutating(self):
        evidence = source_evidence_id("source", "record-1", "a" * 64)
        result = AdvertisingSilverResult(
            brands=[{"brand_id": "brand", "brand_name": "Brand", "organization_id": None}],
            products=[
                {"product_id": "p1", "brand_id": "brand", "product_name": "Face Mask", "source_category_text": None},
                {"product_id": "p2", "brand_id": "brand", "product_name": " face   mask ", "source_category_text": None},
            ],
            campaigns=[{"campaign_id": "campaign", "campaign_name": None, "relationship_type": None, "announced_at": None, "campaign_start_date": None, "campaign_end_date": None, "status": None}],
            campaign_artists=[{"campaign_artist_id": "relationship", "campaign_id": "campaign", "artist_id": RESCENE_ARTIST_ID, "participation_role": "MODEL"}],
            source_evidence=[{
                "source_evidence_id": evidence,
                "source_name": "source",
                "source_type": "OFFICIAL_BRAND",
                "source_url": "https://example.test/record-1",
                "source_record_id": "record-1",
                "collected_at": "2026-09-24T00:00:00Z",
                "published_at": None,
                "content_hash": "a" * 64,
                "authority_level": "OFFICIAL",
                "raw_bronze_reference": "bronze/advertising/official_brand/record-1.json",
                "verification_status": "VERIFIED",
            }],
        )
        issues = assess_advertising_quality(result)
        self.assertEqual(
            {issue.severity for issue in issues},
            {QualitySeverity.WARNING, QualitySeverity.UNRESOLVED},
        )
        self.assertEqual(len(result.products), 2)

    def test_iceberg_merge_uses_canonical_key_for_idempotency(self):
        class Frame:
            def createOrReplaceTempView(self, _view):
                pass

        class Catalog:
            def dropTempView(self, _view):
                pass

        class Spark:
            def __init__(self):
                self.statements = []
                self.catalog = Catalog()

            def createDataFrame(self, _rows, schema):
                return Frame()

            def sql(self, statement):
                self.statements.append(statement)

        schema = type(
            "Schema",
            (),
            {
                "fields": [
                    type("Field", (), {"name": "organization_id"})(),
                    type("Field", (), {"name": "organization_name"})(),
                ]
            },
        )()
        spark = Spark()
        rows = [{"organization_id": "org", "organization_name": "Name"}]
        condition = "target.organization_id = source.organization_id"

        _merge_advertising(
            spark, "advertiser_organization", rows, schema, condition
        )
        _merge_advertising(
            spark, "advertiser_organization", rows, schema, condition
        )

        self.assertEqual(len(spark.statements), 2)
        self.assertTrue(all(f" ON {condition} " in sql for sql in spark.statements))
        self.assertTrue(all("WHEN MATCHED THEN UPDATE" in sql for sql in spark.statements))
        self.assertTrue(all("WHEN NOT MATCHED THEN INSERT" in sql for sql in spark.statements))

    def test_campaign_brand_merge_uses_composite_key(self):
        class Frame:
            def createOrReplaceTempView(self, _view):
                pass

        class Catalog:
            def dropTempView(self, _view):
                pass

        class Spark:
            def __init__(self):
                self.statements = []
                self.catalog = Catalog()

            def createDataFrame(self, _rows, schema):
                return Frame()

            def sql(self, statement):
                self.statements.append(statement)

        schema = type("Schema", (), {"fields": [
            type("Field", (), {"name": "campaign_id"})(),
            type("Field", (), {"name": "brand_id"})(),
        ]})()
        spark = Spark()
        condition = (
            "target.campaign_id = source.campaign_id AND "
            "target.brand_id = source.brand_id"
        )

        _merge_advertising(
            spark,
            "campaign_brand",
            [{"campaign_id": "campaign", "brand_id": "brand"}],
            schema,
            condition,
        )

        self.assertIn(f" ON {condition} ", spark.statements[0])


if __name__ == "__main__":
    unittest.main()
