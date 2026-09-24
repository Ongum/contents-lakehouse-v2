import unittest

from src.advertising_discovery import (
    EvidenceStatus,
    build_candidate,
    candidate_id,
    deduplicate_candidates,
    normalize_discovery_url,
    transition_candidate,
)
from src.advertising_discovery_bronze import (
    AdvertisingDiscoveryBronzeStorage,
    build_discovery_record,
)
from src.advertising_discovery_staging import (
    TABLE_DEFINITION,
    create_candidate_table,
)
from src.advertising_discovery_diagnostic import run_diagnostic
from src.advertising_discovery_pipeline import execute_discovery
from src.advertising_discovery_search import (
    DiscoverySearchPage,
    DiscoverySearchResult,
    GoogleNewsKrRssAdapter,
    parse_google_news_rss,
)
from src.advertising_discovery_staging import CandidatePersistenceResult
from src.advertising_candidate_reader import (
    CandidateFilters,
    print_candidates,
    read_discovered_candidates,
)
from src.advertising_official_evidence import (
    OfficialSourceType,
    build_official_evidence,
    official_evidence_id,
    transition_official_evidence,
)
from src.artist_advertising_watchlist import (
    ArtistWatchlistEntry,
    build_artist_discovery_candidate,
    commercial_relationship_match,
    generate_discovery_queries,
    load_discovery_config,
    resolve_watchlist,
)
from src.mvp_config import RESCENE_ARTIST_ID


class PreconditionFailedError(Exception):
    code = "PreconditionFailed"


class StoredResponse:
    def __init__(self, content):
        self.content = content

    def read(self):
        return self.content

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeClient:
    def __init__(self):
        self.objects = {}
        self.put_count = 0

    def _put_object(self, bucket, object_name, content, headers):
        key = (bucket, object_name)
        if key in self.objects and headers.get("If-None-Match") == "*":
            raise PreconditionFailedError()
        self.objects[key] = content
        self.put_count += 1

    def get_object(self, bucket, object_name):
        return StoredResponse(self.objects[(bucket, object_name)])


def candidate(**overrides):
    values = {
        "discovered_at": "2026-09-24T01:02:03+09:00",
        "discovery_source": "news_search",
        "source_url": "HTTPS://Example.COM/news?id=42&utm_source=test#results",
        "advertiser_brand_text": "Example Brand",
    }
    values.update(overrides)
    return build_candidate(**values)


class AdvertisingDiscoveryTest(unittest.TestCase):
    def test_kr_market_is_enforced(self):
        self.assertEqual(candidate()["market_code"], "KR")
        with self.assertRaisesRegex(ValueError, "must be KR"):
            candidate(market_code="JP")

    def test_candidate_id_is_deterministic_from_source_and_normalized_url(self):
        first = candidate_id(
            "news_search", "HTTPS://Example.COM/news?id=42&utm_source=a#one"
        )
        second = candidate_id(
            "NEWS_SEARCH", "https://example.com/news?id=42&utm_medium=b#two"
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("candidate_"))

    def test_url_normalization_removes_fragment_and_tracking_parameters(self):
        normalized = normalize_discovery_url(
            "HTTPS://Example.COM/Article?utm_source=x&id=42&fbclid=y#section"
        )
        self.assertEqual(normalized, "https://example.com/Article?id=42")

    def test_meaningful_query_parameters_are_preserved(self):
        normalized = normalize_discovery_url(
            "https://example.com/news?board=press&id=672&page=2"
        )
        self.assertEqual(
            normalized, "https://example.com/news?board=press&id=672&page=2"
        )

    def test_duplicate_candidates_are_collapsed_by_identity(self):
        first = candidate(campaign_text="First observation")
        second = candidate(
            source_url="https://example.com/news?id=42&utm_campaign=repeat",
            campaign_text="Repeated observation",
        )
        self.assertEqual(len(deduplicate_candidates([first, second])), 1)

    def test_valid_lifecycle_transitions(self):
        discovered = candidate()
        evidence = build_official_evidence(
            candidate=discovered,
            official_source_url="https://brand.example/campaign?id=42&utm_source=x",
            source_type=OfficialSourceType.BRAND_OFFICIAL,
            found_at="2026-09-24T00:00:00Z",
            verification_reason="Brand campaign page names the artist.",
            official_domains={"brand.example"},
        )
        found = transition_candidate(
            discovered,
            EvidenceStatus.OFFICIAL_SOURCE_FOUND,
            official_evidence=evidence,
        )
        verified_evidence = transition_official_evidence(
            evidence,
            EvidenceStatus.VERIFIED,
            verification_reason="Official page explicitly confirms participation.",
        )
        verified = transition_candidate(
            found, EvidenceStatus.VERIFIED, official_evidence=verified_evidence
        )
        rejected = transition_candidate(
            discovered, EvidenceStatus.REJECTED, rejection_reason="Not a campaign"
        )
        self.assertEqual(verified["evidence_status"], "VERIFIED")
        self.assertEqual(rejected["evidence_status"], "REJECTED")

    def test_verified_is_impossible_without_official_evidence(self):
        discovered = candidate()
        with self.assertRaisesRegex(ValueError, "DISCOVERED -> VERIFIED"):
            transition_candidate(discovered, EvidenceStatus.VERIFIED)
        forged_found = dict(discovered, evidence_status="OFFICIAL_SOURCE_FOUND")
        with self.assertRaisesRegex(ValueError, "requires official evidence"):
            transition_candidate(forged_found, EvidenceStatus.VERIFIED)
        evidence = build_official_evidence(
            candidate=discovered,
            official_source_url="https://brand.example/campaign/42",
            source_type="BRAND_OFFICIAL",
            found_at="2026-09-24T00:00:00Z",
            verification_reason="Official page located.",
            official_domains={"brand.example"},
        )
        with self.assertRaisesRegex(ValueError, "must have VERIFIED status"):
            transition_candidate(
                forged_found, EvidenceStatus.VERIFIED, official_evidence=evidence
            )

    def test_invalid_lifecycle_transitions(self):
        with self.assertRaisesRegex(ValueError, "DISCOVERED -> VERIFIED"):
            transition_candidate(candidate(), EvidenceStatus.VERIFIED)
        rejected = transition_candidate(
            candidate(), EvidenceStatus.REJECTED, rejection_reason="Duplicate"
        )
        with self.assertRaisesRegex(ValueError, "REJECTED ->"):
            transition_candidate(rejected, EvidenceStatus.OFFICIAL_SOURCE_FOUND)

    def test_discovery_bronze_is_separate_and_immutable(self):
        storage = AdvertisingDiscoveryBronzeStorage(FakeClient(), "lakehouse")
        first = build_discovery_record(
            discovery_source="news_search",
            query="리센느 광고 모델",
            source_url="https://example.com/news?id=42&utm_source=x",
            discovered_at="2026-09-24T00:00:00Z",
            raw_content="candidate evidence",
            request_metadata={"method": "GET", "Authorization": "secret"},
        )
        second = build_discovery_record(
            discovery_source="news_search",
            query="리센느 광고 모델",
            source_url="https://example.com/news?id=42",
            discovered_at="2026-09-24T01:00:00Z",
            raw_content="candidate evidence",
        )
        first_name, first_created = storage.write_capture(first)
        original = storage.client.objects[("lakehouse", first_name)]
        second_name, second_created = storage.write_capture(second)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_name, second_name)
        self.assertEqual(storage.client.put_count, 1)
        self.assertEqual(storage.client.objects[("lakehouse", first_name)], original)
        self.assertTrue(first_name.startswith("bronze/advertising_discovery/news_search/"))
        self.assertNotIn(b"secret", original)

    def test_staging_schema_is_separate_and_does_not_create_canonical_silver(self):
        class Table:
            columns = [
                "candidate_id",
                "discovered_for_artist_id",
                "discovered_at",
            ]

        class Spark:
            def __init__(self):
                self.statements = []

            def sql(self, statement):
                self.statements.append(statement)

            def table(self, _table_name):
                return Table()

        spark = Spark()
        table_name = create_candidate_table(spark)
        self.assertEqual(table_name, "lakehouse.staging.advertising_campaign_candidate")
        self.assertIn("market_code STRING NOT NULL", TABLE_DEFINITION)
        self.assertIn("discovered_for_artist_id STRING", TABLE_DEFINITION)
        self.assertIn("discovery_signal STRING", TABLE_DEFINITION)
        self.assertTrue(all("lakehouse.silver" not in sql for sql in spark.statements))
        self.assertTrue(
            all("advertising_campaign (" not in sql for sql in spark.statements)
        )

    def test_initial_watchlist_contains_only_enabled_rescene(self):
        config = load_discovery_config()
        watchlist = resolve_watchlist(
            [{
                "artist_id": RESCENE_ARTIST_ID,
                "artist_name": "RESCENE",
                "artist_type": "GROUP",
            }],
            config,
        )
        self.assertEqual(len(config["artists"]), 1)
        self.assertEqual(len(watchlist), 1)
        self.assertEqual(watchlist[0].artist_id, RESCENE_ARTIST_ID)
        self.assertEqual(watchlist[0].canonical_artist_name, "RESCENE")
        self.assertEqual(watchlist[0].korean_name, "리센느")
        self.assertEqual(watchlist[0].english_name, "RESCENE")
        self.assertEqual(watchlist[0].entity_type, "GROUP")
        self.assertTrue(watchlist[0].discovery_enabled)

    def test_only_enabled_artists_generate_deterministic_kr_queries(self):
        config = load_discovery_config()
        enabled = ArtistWatchlistEntry(
            RESCENE_ARTIST_ID, "RESCENE", "리센느", "RESCENE", "GROUP", True, 100
        )
        disabled = ArtistWatchlistEntry(
            "artist_disabled", "Disabled", "비활성", "Disabled", "PERSON", False, 50
        )
        first = generate_discovery_queries([disabled, enabled], config["query_templates"])
        second = generate_discovery_queries([disabled, enabled], config["query_templates"])
        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        self.assertTrue(all(query.artist_id == RESCENE_ARTIST_ID for query in first))
        self.assertTrue(all(query.market_code == "KR" for query in first))
        self.assertIn("리센느 광고 모델", [query.query_text for query in first])
        self.assertIn("RESCENE 브랜드 협업", [query.query_text for query in first])
        self.assertTrue(
            all("리센느" in query.query_text or "RESCENE" in query.query_text for query in first)
        )
        self.assertNotIn("광고", [query.query_text for query in first])
        self.assertNotIn("광고 캠페인", [query.query_text for query in first])

    def test_artist_candidate_linkage_is_provisional_only(self):
        config = load_discovery_config()
        entry = ArtistWatchlistEntry(
            RESCENE_ARTIST_ID, "RESCENE", "리센느", "RESCENE", "GROUP", True, 100
        )
        result = build_artist_discovery_candidate(
            entry,
            discovery_text="나랑드사이다가 리센느를 광고 모델로 발탁했다.",
            commercial_signals=config["commercial_signals"],
            discovered_at="2026-09-24T00:00:00Z",
            discovery_source="news_search",
            source_url="https://example.com/news?id=7",
            advertiser_brand_text="나랑드사이다",
            campaign_text="리센느 광고 모델 발탁",
            artist_model_text="리센느",
        )
        self.assertEqual(result["discovered_for_artist_id"], RESCENE_ARTIST_ID)
        self.assertNotIn("campaign_artist", result)
        self.assertEqual(result["evidence_status"], "DISCOVERED")

    def test_unrelated_or_incidental_candidate_is_rejected(self):
        config = load_discovery_config()
        entry = ArtistWatchlistEntry(
            RESCENE_ARTIST_ID, "RESCENE", "리센느", "RESCENE", "GROUP", True, 100
        )
        with self.assertRaisesRegex(ValueError, "lacks a plausible"):
            build_artist_discovery_candidate(
                entry,
                discovery_text="리센느가 음악 방송 무대에 출연했다. 광고 업계 동향도 전했다.",
                commercial_signals=config["commercial_signals"],
                discovered_at="2026-09-24T00:00:00Z",
                discovery_source="news_search",
                source_url="https://example.com/news?id=8",
                advertiser_brand_text="기사 내 일반 언급",
            )

    def test_focused_commercial_variants_map_to_canonical_signals(self):
        config = load_discovery_config()
        entry = ArtistWatchlistEntry(
            RESCENE_ARTIST_ID, "RESCENE", "리센느", "RESCENE", "GROUP", True, 100
        )
        cases = {
            "도미노피자, 리센느 전속모델 발탁": "MODEL",
            "도미노피자, 리센느 전속 모델 발탁": "MODEL",
            "도미노피자, 리센느 광고모델 발탁": "MODEL",
            "MLB, 브랜드 모델로 리센느 발탁": "MODEL",
            "MLB, 브랜드모델로 리센느 발탁": "MODEL",
            "바이오던스, 리센느 원이 앰버서더 발탁": "AMBASSADOR",
            "바이오던스, 리센느 원이 앰배서더 발탁": "AMBASSADOR",
            "CU, 리센느와 브랜드 캠페인 진행": "CAMPAIGN",
            "CU, 리센느와 브랜드캠페인 진행": "CAMPAIGN",
            "카카오, 리센느와 일상 속 AI 경험 알린다": "COLLABORATION",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                match = commercial_relationship_match(
                    entry, text, config["commercial_signals"]
                )
                self.assertIsNotNone(match)
                self.assertEqual(match[1], expected)

    def test_broad_collaboration_model_and_ambassador_award_stay_rejected(self):
        config = load_discovery_config()
        entry = ArtistWatchlistEntry(
            RESCENE_ARTIST_ID, "RESCENE", "리센느", "RESCENE", "GROUP", True, 100
        )
        unrelated = (
            "리센느 신곡 제작진이 음악 작업에서 협업했다",
            "리센느가 새 무대에서 모델 이미지를 선보였다",
            "리센느, 스포티비 앰버서더 수상",
        )
        for text in unrelated:
            with self.subTest(text=text):
                self.assertIsNone(
                    commercial_relationship_match(
                        entry, text, config["commercial_signals"]
                    )
                )

    def test_google_news_adapter_parses_fixture_without_network(self):
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item>
          <title>RESCENE selected as brand model - Example News</title>
          <link>https://news.google.com/rss/articles/example?id=1</link>
          <description><![CDATA[<a>RESCENE brand model campaign</a>]]></description>
          <pubDate>Tue, 24 Sep 2026 01:00:00 GMT</pubDate>
        </item></channel></rss>"""
        results = parse_google_news_rss(rss)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].publication_date, "2026-09-24")
        self.assertIn("brand model", results[0].snippet)

        class Response:
            status = 200
            headers = {"Content-Type": "application/rss+xml; charset=UTF-8"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return rss

            def getcode(self):
                return self.status

            def geturl(self):
                return "https://news.google.com/rss/search?q=test"

        adapter = GoogleNewsKrRssAdapter(opener=lambda *_args, **_kwargs: Response())
        self.assertEqual(adapter.fetch_first_page("RESCENE 브랜드 모델"), results)

    def test_diagnostic_deduplicates_and_preserves_discovery_queries(self):
        config = load_discovery_config()
        entry = ArtistWatchlistEntry(
            RESCENE_ARTIST_ID, "RESCENE", "리센느", "RESCENE", "GROUP", True, 100
        )

        class Adapter:
            source_name = "fixture_search"

            def fetch_first_page(self, query):
                return [
                    DiscoverySearchResult(
                        "리센느 광고 모델 발탁",
                        "https://example.com/article?id=1&utm_source=" + query,
                        "브랜드가 리센느를 광고 모델로 발탁했다.",
                        "2026-09-24",
                    ),
                    DiscoverySearchResult(
                        "리센느 음악 방송 출연",
                        "https://example.com/entertainment?id=" + str(len(query)),
                        "새 무대를 선보였다.",
                        "2026-09-24",
                    ),
                ]

        report = run_diagnostic(
            Adapter(),
            [entry],
            config["query_templates"][:2],
            config["commercial_signals"],
            results_per_query=2,
        )
        self.assertEqual(report["total_results_inspected"], 8)
        self.assertGreaterEqual(report["duplicates"], 3)
        self.assertEqual(report["accepted_candidates"], 1)
        self.assertEqual(len(report["accepted"][0].queries), 4)
        self.assertGreaterEqual(report["rejected_results"], 1)

    def test_production_flow_is_write_free_in_dry_run_and_idempotent_normally(self):
        config = load_discovery_config()
        enabled = ArtistWatchlistEntry(
            RESCENE_ARTIST_ID, "RESCENE", "리센느", None, "GROUP", True, 100
        )
        disabled = ArtistWatchlistEntry(
            "disabled", "Disabled", "비활성", None, "PERSON", False, 1
        )

        class Adapter:
            source_name = "fixture_search"

            def __init__(self):
                self.queries = []

            def fetch_first_page_capture(self, query):
                self.queries.append(query)
                results = (
                    DiscoverySearchResult(
                        "도미노피자, 리센느 전속모델 발탁",
                        "https://example.com/domino-one",
                        None,
                        "2026-09-24",
                    ),
                    DiscoverySearchResult(
                        "도미노피자, 리센느 브랜드 모델 발탁",
                        "https://example.com/domino-two",
                        None,
                        "2026-09-24",
                    ),
                    DiscoverySearchResult(
                        "리센느 음악 방송 출연",
                        "https://example.com/entertainment",
                        None,
                        "2026-09-24",
                    ),
                )
                return DiscoverySearchPage(
                    query,
                    "https://search.example?q=" + query,
                    "<rss>fixture</rss>",
                    {"method": "GET"},
                    results,
                )

        class Bronze:
            def __init__(self):
                self.identities = set()
                self.calls = 0

            def write_capture(self, record):
                self.calls += 1
                identity = (record["query"], record["content_hash"])
                created = identity not in self.identities
                self.identities.add(identity)
                return "bronze/object.json", created

        class Staging:
            def __init__(self):
                self.ids = set()
                self.calls = 0
                self.last_rows = []

            def persist(self, rows):
                self.calls += 1
                self.last_rows = rows
                incoming = {row["candidate_id"] for row in rows}
                existing = len(incoming & self.ids)
                self.ids.update(incoming)
                return CandidatePersistenceResult(len(incoming) - existing, existing)

        dry_adapter = Adapter()
        dry_report = execute_discovery(
            adapter=dry_adapter,
            watchlist=[enabled, disabled],
            query_templates=config["query_templates"][:1],
            commercial_signals=config["commercial_signals"],
            discovered_at="2026-09-24T00:00:00Z",
            max_results_per_query=3,
            dry_run=True,
        )
        self.assertEqual(dry_report["bronze_objects_created"], 0)
        self.assertEqual(dry_report["candidate_rows_inserted"], 0)
        self.assertEqual(dry_report["artists_processed"], 1)
        self.assertTrue(all("비활성" not in query for query in dry_adapter.queries))

        bronze = Bronze()
        staging = Staging()
        arguments = {
            "adapter": Adapter(),
            "watchlist": [enabled, disabled],
            "query_templates": config["query_templates"][:1],
            "commercial_signals": config["commercial_signals"],
            "discovered_at": "2026-09-24T00:00:00Z",
            "max_results_per_query": 3,
            "dry_run": False,
            "bronze_storage": bronze,
            "candidate_persister": staging.persist,
        }
        first = execute_discovery(**arguments)
        second = execute_discovery(**arguments)

        self.assertEqual(first["accepted_candidates"], 2)
        self.assertEqual(first["rejected_results"], 1)
        self.assertEqual(first["bronze_objects_created"], 2)
        self.assertEqual(first["candidate_rows_inserted"], 2)
        self.assertEqual(second["candidate_rows_inserted"], 0)
        self.assertEqual(second["candidate_rows_already_existing"], 2)
        self.assertEqual(second["bronze_objects_created"], 0)
        self.assertEqual(len(staging.last_rows), 2)
        self.assertEqual(
            {row["source_url"] for row in staging.last_rows},
            {"https://example.com/domino-one", "https://example.com/domino-two"},
        )
        self.assertTrue(all(row["market_code"] == "KR" for row in staging.last_rows))
        self.assertTrue(
            all(row["evidence_status"] == "DISCOVERED" for row in staging.last_rows)
        )
        self.assertTrue(
            all(
                row["discovered_for_artist_id"] == RESCENE_ARTIST_ID
                for row in staging.last_rows
            )
        )
        self.assertTrue(all("campaign_artist" not in row for row in staging.last_rows))

    def test_official_evidence_identity_and_authority_validation(self):
        discovered = candidate()
        first = build_official_evidence(
            candidate=discovered,
            official_source_url="HTTPS://Brand.Example/campaign?id=7&utm_source=news#top",
            source_type="BRAND_OFFICIAL",
            found_at="2026-09-24T09:00:00+09:00",
            verification_reason="Official brand campaign page.",
            official_domains={"brand.example"},
        )
        second_id = official_evidence_id(
            discovered["candidate_id"],
            "https://brand.example/campaign?id=7",
            OfficialSourceType.BRAND_OFFICIAL,
        )
        self.assertEqual(first["official_evidence_id"], second_id)
        self.assertEqual(first["source_domain"], "brand.example")
        self.assertEqual(first["found_at"], "2026-09-24T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            build_official_evidence(
                candidate=discovered,
                official_source_url="https://news.google.com/article/7",
                source_type="BRAND_OFFICIAL",
                found_at="2026-09-24T00:00:00Z",
                verification_reason="Search result.",
                official_domains={"news.google.com"},
            )
        with self.assertRaises(ValueError):
            build_official_evidence(
                candidate=discovered,
                official_source_url="https://brand.example/campaign/7",
                source_type="MEDIA_ARTICLE",
                found_at="2026-09-24T00:00:00Z",
                verification_reason="Article.",
                official_domains={"brand.example"},
            )
        rejected = transition_official_evidence(
            first,
            EvidenceStatus.REJECTED,
            verification_reason="Official page does not name the watched artist.",
        )
        self.assertEqual(rejected["verification_status"], "REJECTED")
        with self.assertRaisesRegex(ValueError, "REJECTED -> VERIFIED"):
            transition_official_evidence(
                rejected,
                EvidenceStatus.VERIFIED,
                verification_reason="Cannot reopen terminal evidence.",
            )

    def test_multiple_candidates_keep_separate_official_evidence(self):
        first_candidate = candidate(source_url="https://media.example/article/one")
        second_candidate = candidate(source_url="https://media.example/article/two")
        values = []
        for item in (first_candidate, second_candidate):
            values.append(
                build_official_evidence(
                    candidate=item,
                    official_source_url="https://brand.example/campaign/rescene",
                    source_type="CAMPAIGN_OFFICIAL",
                    found_at="2026-09-24T00:00:00Z",
                    verification_reason="Same official campaign page.",
                    official_domains={"brand.example"},
                )
            )
        self.assertNotEqual(
            values[0]["official_evidence_id"], values[1]["official_evidence_id"]
        )
        self.assertEqual(values[0]["official_source_url"], values[1]["official_source_url"])

    def test_discovered_candidate_reader_filters_and_does_not_write(self):
        class Table:
            columns = ["candidate_id", "discovery_signal"]

        class Row:
            def asDict(self, recursive=False):
                return {
                    "candidate_id": "candidate_1",
                    "campaign_text": "리센느 광고 모델",
                    "source_url": "https://example.com/1",
                    "discovery_signal": "MODEL",
                    "discovered_at": "2026-09-24T00:00:00Z",
                }

        class Result:
            def collect(self):
                return [Row()]

        class Spark:
            def __init__(self):
                self.statements = []

            def table(self, name):
                self.table_name = name
                return Table()

            def sql(self, statement):
                self.statements.append(statement)
                return Result()

        spark = Spark()
        rows = read_discovered_candidates(
            spark,
            CandidateFilters(
                candidate_id="candidate_1",
                discovered_for_artist_id="artist_rescene",
                market_code="KR",
            ),
        )
        self.assertEqual(len(rows), 1)
        query = spark.statements[0]
        self.assertIn("evidence_status = 'DISCOVERED'", query)
        self.assertIn("candidate_id = 'candidate_1'", query)
        self.assertIn("discovered_for_artist_id = 'artist_rescene'", query)
        self.assertIn("market_code = 'KR'", query)
        self.assertTrue(query.startswith("SELECT "))
        self.assertNotRegex(query.upper(), r"CREATE|MERGE|INSERT|UPDATE|DELETE")

    def test_inspection_printer_is_read_only_formatting(self):
        from contextlib import redirect_stdout
        from io import StringIO

        rows = [{
            "candidate_id": "candidate_1",
            "campaign_text": "리센느 광고 모델",
            "source_url": "https://example.com/1",
            "discovery_signal": "MODEL",
            "discovered_at": "2026-09-24T00:00:00Z",
        }]
        output = StringIO()
        with redirect_stdout(output):
            print_candidates(rows)
        self.assertIn("candidate_id: candidate_1", output.getvalue())
        self.assertIn("canonical_discovery_signal: MODEL", output.getvalue())


if __name__ == "__main__":
    unittest.main()
