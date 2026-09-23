import unittest

from src.mediawiki_silver import (
    artist_id_for_member,
    extract_current_members,
    extract_release_events,
    transform_mediawiki_bronze,
)
from src.mvp_config import RESCENE_ARTIST_ID


WIKITEXT = """{{Infobox musical artist
| years_active = 2024-present
| current_members =
* Woni
* Liv
* Minami
* May
* Zena
}}
==Members==
* Woni
* Liv
* Minami
* May
* Zena
==Discography==
{| class="wikitable"
! scope="row" | ''Scenedrome''
|
* Released: August 27, 2024
* Label: The Muze
|-
! scope="row" | ''[[Re:Scene]]''
|
* Released: March 26, 2024
|-
! scope="row" | ''Future Album''
|
* Scheduled: November 3, 2026
|}
"""


def envelope(wikitext=WIKITEXT, parent_revision_id=1376088054):
    return {
        "source": "mediawiki",
        "edition": "en",
        "page_id": 76400327,
        "canonical_title": "Rescene",
        "revision_id": 1376088055,
        "parent_revision_id": parent_revision_id,
        "revision_timestamp": "2026-09-22T00:27:05Z",
        "ingested_at": "2026-09-23T03:30:00Z",
        "raw_wikitext": wikitext,
    }


class MediaWikiSilverTest(unittest.TestCase):
    def test_extracts_only_structured_current_members(self):
        self.assertEqual(
            extract_current_members(WIKITEXT),
            ["Woni", "Liv", "Minami", "May", "Zena"],
        )

    def test_artist_ids_are_deterministic_and_not_names(self):
        first = artist_id_for_member("Woni")
        second = artist_id_for_member("Woni")

        self.assertEqual(first, second)
        self.assertNotEqual(first, "Woni")
        self.assertTrue(first.startswith("artist_"))

    def test_extracts_only_explicit_release_dates(self):
        releases = extract_release_events(WIKITEXT)

        self.assertEqual(
            releases,
            [
                {"event_name": "Re:Scene", "release_date": "2024-03-26"},
                {"event_name": "Scenedrome", "release_date": "2024-08-27"},
            ],
        )

    def test_builds_artists_relationships_events_and_lineage(self):
        result = transform_mediawiki_bronze("bronze/mediawiki/page.json", envelope())

        self.assertFalse(result.invalid_records)
        self.assertEqual(len(result.artists), 6)
        self.assertEqual(result.artists[0]["artist_id"], RESCENE_ARTIST_ID)
        self.assertEqual(result.artists[0]["artist_type"], "GROUP")
        self.assertEqual(
            [row["artist_name"] for row in result.artists[1:]],
            ["Woni", "Liv", "Minami", "May", "Zena"],
        )
        self.assertEqual(len(result.artist_relationships), 5)
        self.assertTrue(
            all(
                row["relationship_type"] == "MEMBER_OF"
                and row["to_artist_id"] == RESCENE_ARTIST_ID
                and row["start_date"] is None
                and row["end_date"] is None
                for row in result.artist_relationships
            )
        )
        self.assertEqual(len(result.artist_events), 2)
        self.assertTrue(
            all(
                row["event_type"] == "RELEASE"
                and row["start_precision"] == "DATE"
                for row in result.artist_events
            )
        )
        self.assertEqual(len(result.event_artists), 2)
        self.assertEqual(
            result.artist_external_identifiers[0]["external_id"], "en:76400327"
        )
        self.assertTrue(
            all(row["revision_id"] == 1376088055 for row in result.lineage)
        )

    def test_event_and_relationship_ids_are_idempotent_on_rerun(self):
        first = transform_mediawiki_bronze("bronze/first.json", envelope())
        second = transform_mediawiki_bronze("bronze/first.json", envelope())

        self.assertEqual(first.artists, second.artists)
        self.assertEqual(first.artist_relationships, second.artist_relationships)
        self.assertEqual(first.artist_events, second.artist_events)
        self.assertEqual(first.event_artists, second.event_artists)

    def test_missing_optional_parent_revision_is_allowed(self):
        result = transform_mediawiki_bronze(
            "bronze/mediawiki/page.json", envelope(parent_revision_id=None)
        )

        self.assertFalse(result.invalid_records)
        self.assertEqual(len(result.artists), 6)

    def test_missing_structured_members_is_reported(self):
        result = transform_mediawiki_bronze(
            "bronze/mediawiki/page.json", envelope("==History==\nNo infobox")
        )

        self.assertFalse(result.artists)
        self.assertEqual(len(result.invalid_records), 1)
        self.assertIn(
            "current_members", result.invalid_records[0]["error_message"]
        )


if __name__ == "__main__":
    unittest.main()
