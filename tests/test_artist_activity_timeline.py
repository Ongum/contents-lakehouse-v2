import unittest

from src.artist_activity_timeline import (
    ArtistActivityTimelineResult,
    project_artist_activity_timeline,
    timeline_event_id,
    validate_artist_activity_timeline,
)
from src.artist_activity_timeline_iceberg import _merge
from src.artist_activity_timeline_iceberg import _validate_source_evidence_references


ARTIST_ID = "artist_rescene"
EVIDENCE_ID = "evidence_official_1"


def project(**overrides):
    values = {
        "artist_ids": [ARTIST_ID],
        "youtube_channels": [
            {"channel_id": "channel-1", "artist_id": ARTIST_ID}
        ],
        "youtube_videos": [
            {
                "video_id": "video-1",
                "channel_id": "channel-1",
                "title": "MV",
                "published_at": "2026-09-20T02:00:00+00:00",
            }
        ],
        "video_metrics_snapshots": [
            {"video_id": "video-1", "observed_at": "2026-09-20T03:00:00Z"}
        ],
        "youtube_lineage": [
            {
                "record_type": "youtube_video",
                "record_key": ("video-1",),
                "source_reference": "bronze/youtube/video-1.json",
            }
        ],
        "artist_events": [
            {
                "event_id": "release-1",
                "event_type": "RELEASE",
                "event_name": "Re:Scene",
                "start_at": "2024-03-26T00:00:00Z",
                "start_precision": "date",
                "source_url": "https://example.test/artist",
            }
        ],
        "event_artists": [{"event_id": "release-1", "artist_id": ARTIST_ID}],
        "advertising_campaigns": [
            {
                "campaign_id": "campaign-1",
                "campaign_name": "Official campaign",
                "announced_at": None,
                "campaign_start_date": None,
                "campaign_end_date": None,
            }
        ],
        "campaign_artists": [
            {
                "campaign_artist_id": "campaign-artist-1",
                "campaign_id": "campaign-1",
                "artist_id": ARTIST_ID,
                "participation_role": "MODEL",
            }
        ],
        "source_evidence": [
            {
                "source_evidence_id": EVIDENCE_ID,
                "source_url": "https://brand.example/news/1",
                "published_at": "2026-08-27T00:00:00Z",
                "collected_at": "2026-09-24T01:00:00Z",
            }
        ],
        "canonical_field_evidence": [
            {
                "entity_type": "CAMPAIGN_ARTIST",
                "entity_id": "campaign-artist-1",
                "field_name": "participation_role",
                "source_evidence_id": EVIDENCE_ID,
                "is_selected": True,
            }
        ],
    }
    values.update(overrides)
    return project_artist_activity_timeline(**values)


class ArtistActivityTimelineTests(unittest.TestCase):
    def test_projects_supported_domains_with_explicit_temporal_semantics(self):
        result = project()

        self.assertEqual(
            [row["event_type"] for row in result.events],
            ["RELEASE", "OFFICIAL_EVIDENCE_PUBLISHED", "VIDEO_PUBLISHED"],
        )
        release, publication, video = result.events
        self.assertEqual(release["temporal_precision"], "DATE")
        self.assertEqual(release["time_semantics"], "EVENT_TIME")
        self.assertEqual(video["event_at"], "2026-09-20T02:00:00Z")
        self.assertEqual(video["temporal_precision"], "TIMESTAMP")
        self.assertEqual(video["observed_at"], "2026-09-20T03:00:00Z")
        self.assertEqual(publication["time_semantics"], "PUBLICATION_TIME")
        self.assertEqual(publication["source_reference"], "https://brand.example/news/1")

    def test_publication_date_does_not_become_effective_campaign_date(self):
        result = project()

        self.assertNotIn(
            "CAMPAIGN_STARTED", {row["event_type"] for row in result.events}
        )
        self.assertNotIn(
            "CAMPAIGN_ENDED", {row["event_type"] for row in result.events}
        )

    def test_explicit_campaign_dates_are_date_precision_and_field_provenance(self):
        campaigns = [
            {
                "campaign_id": "campaign-1",
                "campaign_name": "Official campaign",
                "announced_at": "2026-08-20T12:30:00+09:00",
                "campaign_start_date": "2026-09-01",
                "campaign_end_date": "2026-09-30",
            }
        ]
        canonical_evidence = [
            {
                "entity_type": "CAMPAIGN_ARTIST",
                "entity_id": "campaign-artist-1",
                "field_name": "participation_role",
                "source_evidence_id": EVIDENCE_ID,
                "is_selected": True,
            },
            {
                "entity_type": "CAMPAIGN",
                "entity_id": "campaign-1",
                "field_name": "campaign_start_date",
                "source_evidence_id": EVIDENCE_ID,
                "is_selected": True,
            },
        ]
        result = project(
            advertising_campaigns=campaigns,
            canonical_field_evidence=canonical_evidence,
        )

        by_type = {row["event_type"]: row for row in result.events}
        self.assertEqual(by_type["CAMPAIGN_ANNOUNCED"]["event_at"], "2026-08-20T03:30:00Z")
        self.assertEqual(by_type["CAMPAIGN_ANNOUNCED"]["time_semantics"], "EVENT_TIME")
        self.assertEqual(by_type["CAMPAIGN_STARTED"]["event_at"], "2026-09-01T00:00:00Z")
        self.assertEqual(by_type["CAMPAIGN_STARTED"]["temporal_precision"], "DATE")
        self.assertEqual(by_type["CAMPAIGN_STARTED"]["time_semantics"], "EFFECTIVE_TIME")
        start_id = by_type["CAMPAIGN_STARTED"]["timeline_event_id"]
        self.assertIn(
            {"timeline_event_id": start_id, "source_evidence_id": EVIDENCE_ID},
            result.event_evidence,
        )
        announcement_id = by_type["CAMPAIGN_ANNOUNCED"]["timeline_event_id"]
        self.assertNotIn(
            {"timeline_event_id": announcement_id, "source_evidence_id": EVIDENCE_ID},
            result.event_evidence,
        )

    def test_projection_is_deterministic_idempotent_and_deduplicates_same_fact(self):
        first = project()
        second = project(youtube_videos=project_source_videos() * 2)

        self.assertEqual(first, project())
        self.assertEqual(first.events, second.events)
        self.assertEqual(first.event_evidence, second.event_evidence)

    def test_event_identity_encoding_is_unambiguous_with_delimiters(self):
        first = timeline_event_id(
            ARTIST_ID, "ARTIST_EVENT", "ARTIST_EVENT", "event:a", "b"
        )
        second = timeline_event_id(
            ARTIST_ID, "ARTIST_EVENT", "ARTIST_EVENT", "event", "a:b"
        )

        self.assertNotEqual(first, second)
        self.assertEqual(
            first,
            timeline_event_id(
                ARTIST_ID, "ARTIST_EVENT", "ARTIST_EVENT", "event:a", "b"
            ),
        )

    def test_null_artist_event_start_does_not_require_precision_or_emit_event(self):
        result = project(
            youtube_videos=[],
            video_metrics_snapshots=[],
            artist_events=[{
                "event_id": "unknown-time",
                "event_type": "APPEARANCE",
                "event_name": "Unknown date appearance",
                "start_at": None,
                "start_precision": None,
                "end_at": None,
                "source_url": None,
            }],
            event_artists=[{
                "event_id": "unknown-time",
                "artist_id": ARTIST_ID,
            }],
            advertising_campaigns=[],
            campaign_artists=[],
            source_evidence=[],
            canonical_field_evidence=[],
        )

        self.assertEqual(result.events, [])

    def test_invalid_artist_and_source_references_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "artist reference"):
            project(artist_ids=["another-artist"])
        with self.assertRaisesRegex(ValueError, "canonical field evidence reference"):
            project(canonical_field_evidence=[{
                "entity_type": "CAMPAIGN_ARTIST",
                "entity_id": "campaign-artist-1",
                "field_name": "participation_role",
                "source_evidence_id": "missing",
                "is_selected": True,
            }])

    def test_duplicate_inputs_and_invalid_date_order_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate YouTube channel"):
            project(youtube_channels=[
                {"channel_id": "channel-1", "artist_id": ARTIST_ID},
                {"channel_id": "channel-1", "artist_id": ARTIST_ID},
            ])
        with self.assertRaisesRegex(ValueError, "campaign_start_date"):
            project(advertising_campaigns=[{
                "campaign_id": "campaign-1",
                "campaign_name": "Campaign",
                "announced_at": None,
                "campaign_start_date": "2026-09-30",
                "campaign_end_date": "2026-09-01",
            }])

    def test_precision_event_type_and_evidence_integrity_are_validated(self):
        event = {
            "timeline_event_id": timeline_event_id(
                ARTIST_ID, "YOUTUBE", "YOUTUBE_VIDEO", "video-1", "VIDEO_PUBLISHED"
            ),
            "artist_id": ARTIST_ID,
            "event_type": "VIDEO_PUBLISHED",
            "event_name": "MV",
            "event_at": "2026-09-20T02:00:00Z",
            "temporal_precision": "DATE",
            "time_semantics": "PUBLICATION_TIME",
            "observed_at": None,
            "source_domain": "YOUTUBE",
            "source_entity_type": "YOUTUBE_VIDEO",
            "source_entity_id": "video-1",
            "source_reference": None,
        }
        with self.assertRaisesRegex(ValueError, "precision or time semantics"):
            validate_artist_activity_timeline(
                ArtistActivityTimelineResult(events=[event]), [ARTIST_ID]
            )
        event.update({
            "timeline_event_id": timeline_event_id(
                ARTIST_ID, "ARTIST_EVENT", "ARTIST_EVENT", "release-1", "RELEASE"
            ),
            "event_type": "RELEASE",
            "temporal_precision": "DATE",
            "time_semantics": "EVENT_TIME",
            "source_domain": "ARTIST_EVENT",
            "source_entity_type": "ARTIST_EVENT",
            "source_entity_id": "release-1",
        })
        with self.assertRaisesRegex(ValueError, "UTC midnight"):
            validate_artist_activity_timeline(
                ArtistActivityTimelineResult(events=[event]), [ARTIST_ID]
            )
        event.update({
            "timeline_event_id": timeline_event_id(
                ARTIST_ID, "YOUTUBE", "YOUTUBE_VIDEO", "video-1", "VIDEO_PUBLISHED"
            ),
            "event_type": "VIDEO_PUBLISHED",
            "source_domain": "YOUTUBE",
            "source_entity_type": "YOUTUBE_VIDEO",
            "source_entity_id": "video-1",
        })
        event["temporal_precision"] = "TIMESTAMP"
        event["time_semantics"] = "EFFECTIVE_TIME"
        with self.assertRaisesRegex(ValueError, "precision or time semantics"):
            validate_artist_activity_timeline(
                ArtistActivityTimelineResult(events=[event]), [ARTIST_ID]
            )
        event["time_semantics"] = "PUBLICATION_TIME"
        event["temporal_precision"] = "TIMESTAMP"
        event["event_type"] = "CAMPAIGN_STARTED"
        with self.assertRaisesRegex(ValueError, "source-domain/event-type"):
            validate_artist_activity_timeline(
                ArtistActivityTimelineResult(events=[event]), [ARTIST_ID]
            )
        with self.assertRaisesRegex(ValueError, "evidence reference"):
            validate_artist_activity_timeline(
                ArtistActivityTimelineResult(
                    event_evidence=[{
                        "timeline_event_id": "missing",
                        "source_evidence_id": EVIDENCE_ID,
                    }]
                ),
                [ARTIST_ID],
            )

    def test_merge_uses_stable_event_key(self):
        class Frame:
            def createOrReplaceTempView(self, _name):
                pass

        class Catalog:
            def dropTempView(self, _name):
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
            type("Field", (), {"name": "timeline_event_id"})(),
            type("Field", (), {"name": "artist_id"})(),
        ]})()
        spark = Spark()
        _merge(
            spark,
            "artist_activity_timeline",
            [{"timeline_event_id": "event", "artist_id": ARTIST_ID}],
            schema,
            "target.timeline_event_id = source.timeline_event_id",
        )
        self.assertIn(
            "ON target.timeline_event_id = source.timeline_event_id",
            spark.statements[0],
        )

    def test_persistence_rejects_orphan_source_evidence(self):
        class EvidenceRow:
            source_evidence_id = "canonical-evidence"

        class Table:
            def select(self, _column):
                return self

            def collect(self):
                return [EvidenceRow()]

        class Spark:
            def table(self, _name):
                return Table()

        valid = ArtistActivityTimelineResult(
            event_evidence=[{
                "timeline_event_id": "event",
                "source_evidence_id": "canonical-evidence",
            }]
        )
        _validate_source_evidence_references(Spark(), valid)

        orphan = ArtistActivityTimelineResult(
            event_evidence=[{
                "timeline_event_id": "event",
                "source_evidence_id": "missing-evidence",
            }]
        )
        with self.assertRaisesRegex(ValueError, "missing canonical"):
            _validate_source_evidence_references(Spark(), orphan)


def project_source_videos():
    return [
        {
            "video_id": "video-1",
            "channel_id": "channel-1",
            "title": "MV",
            "published_at": "2026-09-20T02:00:00+00:00",
        }
    ]


if __name__ == "__main__":
    unittest.main()
