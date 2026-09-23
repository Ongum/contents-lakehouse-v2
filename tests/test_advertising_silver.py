import unittest

from src.advertising_silver import (
    brand_id,
    campaign_id,
    organization_id,
    transform_advertising_bronze,
)
from src.advertising_silver_iceberg import _merge_advertising
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

    def test_source_category_text_is_preserved_without_normalized_taxonomy(self):
        content = ARTICLE + "<div>제품 카테고리: 제로칼로리 탄산음료.</div>"
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope(content))

        self.assertEqual(
            result.products[0]["source_category_text"], "제로칼로리 탄산음료"
        )
        self.assertEqual(
            result.product_categories,
            [
                {
                    "category_id": result.product_categories[0]["category_id"],
                    "source_category_text": "제로칼로리 탄산음료",
                }
            ],
        )

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

    def test_only_explicit_metrics_are_created_without_causal_inference(self):
        result = transform_advertising_bronze(SOURCE_REFERENCE, envelope())
        metrics = {row["metric_type"]: row for row in result.market_metrics}

        self.assertEqual(metrics["SALES_GROWTH"]["value"], 48.0)
        self.assertEqual(metrics["SALES_GROWTH"]["unit"], "PERCENT")
        self.assertEqual(metrics["SALES_GROWTH"]["comparison_type"], "YOY")
        self.assertIsNone(metrics["SALES_GROWTH"]["measurement_start"])
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
            campaign_id("brand", "AMBASSADOR", RESCENE_ARTIST_ID)

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


if __name__ == "__main__":
    unittest.main()
