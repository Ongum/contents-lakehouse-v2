import unittest
from dataclasses import replace
from pathlib import Path

from src.advertising_official_ingestion import (
    DominoNewsAdapter,
    DongAOtsukaNewsAdapter,
    canonical_mapping_plan,
    minimal_bronze_evidence,
    minimal_bronze_object_name,
    normalize_relationship,
    validate_official_evidence,
)
from src.advertising_official_silver import (
    project_gold_artist_commercial_intelligence,
    transform_official_evidence,
)
from src.advertising_silver import brand_id, campaign_id
from src.advertising_silver_iceberg import validate_advertising_silver_result
from src.mvp_config import RESCENE_ARTIST_ID


FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED_AT = "2026-09-24T03:00:00Z"


class OfficialAdvertisingIngestionTest(unittest.TestCase):
    def fixture(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_donga_extracts_stable_identity_rescene_and_model(self):
        evidence = DongAOtsukaNewsAdapter().parse(
            self.fixture("advertising_official_donga_672.html"),
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(evidence.source_record_id, "idx=672")
        self.assertEqual(evidence.artist_name, "RESCENE")
        self.assertEqual(evidence.artist_entity_scope, "GROUP")
        self.assertEqual(evidence.relationship_type, "MODEL")
        self.assertEqual(evidence.brand_name, "Narangd Cider")
        self.assertIsNone(evidence.product_name)
        self.assertIsNone(evidence.relationship_start_date)

    def test_domino_preserves_exclusivity_and_does_not_invent_product(self):
        evidence = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"),
            observed_at=OBSERVED_AT,
        )

        self.assertEqual(evidence.source_record_id, "idx=3230")
        self.assertEqual(evidence.artist_name, "RESCENE")
        self.assertEqual(evidence.relationship_type, "MODEL")
        self.assertIn("전속 모델", evidence.relationship_source_text)
        self.assertIsNone(evidence.product_name)
        self.assertIsNone(canonical_mapping_plan(evidence)["campaign_product"])

    def test_relationship_normalization_is_explicit_and_unknown_is_null(self):
        self.assertEqual(normalize_relationship("브랜드 모델로 발탁"), "MODEL")
        self.assertEqual(normalize_relationship("공식 앰버서더로 선정"), "AMBASSADOR")
        self.assertIsNone(normalize_relationship("리센느와 캠페인을 공개했다"))
        self.assertIsNone(normalize_relationship("광고에 등장했다"))

    def test_evidence_identity_and_url_normalization_are_deterministic(self):
        first = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        second = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        self.assertEqual(first.evidence_id, second.evidence_id)
        payload = minimal_bronze_evidence(first)
        self.assertEqual(payload["source_url"], first.source_url)
        self.assertNotIn("raw_content", payload)
        self.assertTrue(minimal_bronze_object_name(first).endswith("/evidence.json"))

    def test_publication_date_is_not_promoted_to_effective_date(self):
        evidence = DongAOtsukaNewsAdapter().parse(
            self.fixture("advertising_official_donga_672.html"), observed_at=OBSERVED_AT
        )
        self.assertEqual(evidence.published_at, "2026-08-27")
        self.assertIsNone(evidence.relationship_start_date)
        self.assertIsNone(evidence.campaign_start_date)

    def test_invalid_ordering_and_unsupported_claim_fail(self):
        evidence = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        with self.assertRaisesRegex(ValueError, "relationship_start_date"):
            validate_official_evidence(replace(
                evidence,
                relationship_start_date="2026-09-02",
                relationship_end_date="2026-09-01",
            ))
        with self.assertRaisesRegex(ValueError, "supporting source wording"):
            validate_official_evidence(replace(
                evidence,
                relationship_source_text="campaign appearance",
            ))

    def test_minimal_provenance_preserves_evidence_reference(self):
        evidence = DongAOtsukaNewsAdapter().parse(
            self.fixture("advertising_official_donga_672.html"), observed_at=OBSERVED_AT
        )
        payload = minimal_bronze_evidence(evidence)
        self.assertEqual(payload["evidence"]["content_hash"], evidence.content_hash)
        self.assertEqual(canonical_mapping_plan(evidence)["source_evidence"], evidence.evidence_id)

    def test_shared_transform_preserves_donga_legacy_ids_and_provenance(self):
        evidence = DongAOtsukaNewsAdapter().parse(
            self.fixture("advertising_official_donga_672.html"), observed_at=OBSERVED_AT
        )
        transformed = transform_official_evidence(
            evidence, bronze_reference="bronze/advertising/fixture/donga.json"
        )
        silver = transformed.silver
        expected_brand = brand_id("Narangd Cider")
        expected_campaign = campaign_id(expected_brand, "MODEL", RESCENE_ARTIST_ID)

        self.assertEqual(silver.brands[0]["brand_id"], expected_brand)
        self.assertEqual(silver.campaigns[0]["campaign_id"], expected_campaign)
        self.assertEqual(
            silver.campaign_brands,
            [{"campaign_id": expected_campaign, "brand_id": expected_brand}],
        )
        self.assertEqual(silver.campaigns[0]["relationship_type"], "MODEL")
        self.assertEqual(silver.campaign_artists[0]["participation_role"], "MODEL")
        self.assertEqual(silver.source_evidence[0]["source_evidence_id"], evidence.evidence_id)
        self.assertTrue(silver.canonical_field_evidence)
        validate_advertising_silver_result(silver)

    def test_domino_uses_same_transform_with_nullable_product_and_organization(self):
        evidence = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        transformed = transform_official_evidence(
            evidence, bronze_reference="bronze/advertising/fixture/domino.json"
        )
        silver = transformed.silver

        self.assertEqual(silver.brands[0]["brand_id"], brand_id("Domino's Pizza"))
        self.assertIsNone(silver.brands[0]["organization_id"])
        self.assertFalse(silver.organizations)
        self.assertFalse(silver.products)
        self.assertEqual(silver.campaign_artists[0]["artist_id"], RESCENE_ARTIST_ID)
        self.assertEqual(silver.campaign_artists[0]["participation_role"], "MODEL")
        self.assertEqual(
            silver.campaign_brands,
            [{
                "campaign_id": silver.campaigns[0]["campaign_id"],
                "brand_id": brand_id("Domino's Pizza"),
            }],
        )
        self.assertIn(
            "전속 모델",
            next(
                row["selection_reason"]
                for row in silver.canonical_field_evidence
                if row["field_name"] == "participation_role"
            ),
        )
        validate_advertising_silver_result(silver)

    def test_shared_transform_is_deterministic_and_source_independent(self):
        evidence = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        first = transform_official_evidence(evidence, bronze_reference="bronze/a.json")
        second = transform_official_evidence(evidence, bronze_reference="bronze/a.json")
        self.assertEqual(first, second)
        self.assertEqual(len({row["brand_id"] for row in first.silver.brands}), 1)
        self.assertEqual(len({row["campaign_id"] for row in first.silver.campaigns}), 1)
        self.assertEqual(
            len({row["campaign_artist_id"] for row in first.silver.campaign_artists}), 1
        )
        self.assertEqual(first.silver.campaign_brands, second.silver.campaign_brands)

        alternate_source = replace(
            evidence,
            source_name="Another official page",
            source_record_id="record-2",
            source_url="https://official.example/record-2",
        )
        alternate = transform_official_evidence(
            alternate_source, bronze_reference="bronze/b.json"
        )
        self.assertEqual(
            first.silver.campaigns[0]["campaign_id"],
            alternate.silver.campaigns[0]["campaign_id"],
        )
        self.assertNotEqual(
            first.silver.source_evidence[0]["source_evidence_id"],
            alternate.silver.source_evidence[0]["source_evidence_id"],
        )

    def test_unknown_entities_remain_unresolved(self):
        evidence = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        unknown = replace(evidence, artist_name="Unknown Artist", brand_name="Unknown Brand")
        transformed = transform_official_evidence(
            unknown, bronze_reference="bronze/unknown.json"
        )
        self.assertFalse(transformed.silver.brands)
        self.assertFalse(transformed.silver.campaigns)
        self.assertFalse(transformed.silver.campaign_artists)
        self.assertIn(
            "unknown_artist", {issue.rule for issue in transformed.quality_issues}
        )
        self.assertIn(
            "unknown_brand", {issue.rule for issue in transformed.quality_issues}
        )

    def test_gold_projection_retains_null_product_and_market(self):
        evidence = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        silver = transform_official_evidence(
            evidence, bronze_reference="bronze/domino.json"
        ).silver
        # Provenance remains, but the business join must work without using it.
        silver.canonical_field_evidence = []
        rows = project_gold_artist_commercial_intelligence(silver)

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["product_id"])
        self.assertIsNone(rows[0]["market_code"])
        self.assertTrue(rows[0]["has_official_evidence"])
        self.assertTrue(rows[0]["unresolved_flag"])

    def test_quality_reports_optional_gaps_without_failing_record(self):
        evidence = DominoNewsAdapter().parse(
            self.fixture("advertising_official_domino_3230.html"), observed_at=OBSERVED_AT
        )
        transformed = transform_official_evidence(
            evidence, bronze_reference="bronze/domino.json"
        )
        rules = {issue.rule for issue in transformed.quality_issues}
        self.assertIn("unresolved_product", rules)
        self.assertIn("unresolved_market", rules)
        self.assertIn("publication_without_effective_date", rules)
        self.assertIn("organization_unresolved", rules)
        self.assertTrue(transformed.silver.campaign_artists)


if __name__ == "__main__":
    unittest.main()
