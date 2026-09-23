"""Transform persisted MediaWiki Bronze wikitext into canonical Silver records."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

if __package__:
    from .mvp_config import RESCENE_ARTIST_ID
else:
    from mvp_config import RESCENE_ARTIST_ID


MEMBER_NAMES = ("Woni", "Liv", "Minami", "May", "Zena")
MEDIAWIKI_PREFIX = "bronze/mediawiki/en/"


@dataclass
class MediaWikiSilverResult:
    artists: list[dict[str, Any]] = field(default_factory=list)
    artist_external_identifiers: list[dict[str, Any]] = field(default_factory=list)
    artist_relationships: list[dict[str, Any]] = field(default_factory=list)
    artist_events: list[dict[str, Any]] = field(default_factory=list)
    event_artists: list[dict[str, Any]] = field(default_factory=list)
    lineage: list[dict[str, Any]] = field(default_factory=list)
    invalid_records: list[dict[str, Any]] = field(default_factory=list)


class MediaWikiTransformError(ValueError):
    """Raised when one MediaWiki Bronze revision cannot be transformed safely."""


def _stable_id(kind: str, identity: str) -> str:
    return f"{kind}_{uuid5(NAMESPACE_URL, f'contents-lakehouse:{kind}:{identity}').hex}"


def artist_id_for_member(member_name: str) -> str:
    """Return a deterministic internal ID scoped to RESCENE membership."""
    normalized = " ".join(member_name.casefold().split())
    return _stable_id("artist", f"{RESCENE_ARTIST_ID}:member:{normalized}")


def relationship_id(from_artist_id: str, to_artist_id: str) -> str:
    return _stable_id(
        "relationship", f"{from_artist_id}:MEMBER_OF:{to_artist_id}"
    )


def release_event_id(title: str, release_date: str) -> str:
    normalized_title = " ".join(title.casefold().split())
    return _stable_id(
        "event", f"{RESCENE_ARTIST_ID}:RELEASE:{normalized_title}:{release_date}"
    )


def extract_current_members(wikitext: str) -> list[str]:
    if not isinstance(wikitext, str):
        raise MediaWikiTransformError("raw_wikitext must be a string.")
    match = re.search(
        r"(?ms)^\|\s*current_members\s*=\s*(.*?)(?=^\|\s*\w|^}})",
        wikitext,
    )
    if match is None:
        raise MediaWikiTransformError("Missing structured current_members field.")
    members = []
    for line in match.group(1).splitlines():
        bullet = re.match(r"^\s*\*\s*([^\[{<|]+?)\s*$", line)
        if bullet:
            members.append(bullet.group(1).strip())
    if not members:
        raise MediaWikiTransformError("Structured current_members field is empty.")
    return members


def _plain_title(value: str) -> str:
    title = value.strip()
    title = re.sub(r"'{2,}", "", title)
    link = re.fullmatch(r"\[\[(?:[^]|]+\|)?([^]]+)]]", title)
    if link:
        title = link.group(1)
    return title.strip()


def extract_release_events(wikitext: str) -> list[dict[str, str]]:
    """Parse only wikitable rows containing an explicit Released date."""
    if not isinstance(wikitext, str):
        raise MediaWikiTransformError("raw_wikitext must be a string.")
    events: dict[tuple[str, str], dict[str, str]] = {}
    rows = re.finditer(
        r'(?ms)^!\s*scope="row"\s*\|\s*(?P<title>[^\n]+)\n'
        r"(?P<body>.*?)(?=^\|-\s*$|^\|}\s*$)",
        wikitext,
    )
    for row in rows:
        released = re.search(
            r"(?m)^\s*\*\s*Released:\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s*$",
            row.group("body"),
        )
        if released is None:
            continue
        try:
            parsed = datetime.strptime(released.group(1), "%B %d, %Y")
        except ValueError:
            continue
        title = _plain_title(row.group("title"))
        if not title:
            continue
        release_date = parsed.date().isoformat()
        events[(title, release_date)] = {
            "event_name": title,
            "release_date": release_date,
        }
    return [events[key] for key in sorted(events, key=lambda item: (item[1], item[0]))]


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MediaWikiTransformError(f"Missing required {field}.")
    return value


def _positive_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MediaWikiTransformError(f"Invalid {field}.")
    return value


def _utc_timestamp(value: Any, field: str) -> str:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise MediaWikiTransformError(f"Invalid {field}.") from error
    if parsed.tzinfo is None:
        raise MediaWikiTransformError(f"Invalid {field}: timezone is required.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _lineage(
    record_type: str,
    record_key: str,
    edition: str,
    page_id: int,
    revision_id: int,
    source_reference: str,
) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "record_key": record_key,
        "edition": edition,
        "page_id": page_id,
        "revision_id": revision_id,
        "source_reference": source_reference,
    }


def transform_mediawiki_bronze(
    source_reference: str, envelope: dict[str, Any]
) -> MediaWikiSilverResult:
    result = MediaWikiSilverResult()
    try:
        if not isinstance(envelope, dict):
            raise MediaWikiTransformError("Bronze envelope must be an object.")
        if envelope.get("source") != "mediawiki" or envelope.get("edition") != "en":
            raise MediaWikiTransformError("Unsupported MediaWiki source or edition.")
        page_id = _positive_integer(envelope.get("page_id"), "page_id")
        revision_id = _positive_integer(envelope.get("revision_id"), "revision_id")
        canonical_title = _required_text(
            envelope.get("canonical_title"), "canonical_title"
        )
        _utc_timestamp(envelope.get("revision_timestamp"), "revision_timestamp")
        _utc_timestamp(envelope.get("ingested_at"), "ingested_at")
        wikitext = _required_text(envelope.get("raw_wikitext"), "raw_wikitext")
        members = extract_current_members(wikitext)
        releases = extract_release_events(wikitext)
    except MediaWikiTransformError as error:
        result.invalid_records.append(
            {
                "pipeline_stage": "bronze_to_silver",
                "source_reference": source_reference,
                "error_type": "record_validation_error",
                "error_message": str(error),
            }
        )
        return result

    unexpected = [name for name in members if name not in MEMBER_NAMES]
    missing = [name for name in MEMBER_NAMES if name not in members]
    if unexpected or missing:
        details = []
        if missing:
            details.append(f"missing expected members: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected members: {', '.join(unexpected)}")
        result.invalid_records.append(
            {
                "pipeline_stage": "bronze_to_silver",
                "source_reference": source_reference,
                "error_type": "member_validation_error",
                "error_message": "; ".join(details),
            }
        )
        return result

    page_url = f"https://en.wikipedia.org/wiki/{quote(canonical_title.replace(' ', '_'))}"
    result.artists.append(
        {
            "artist_id": RESCENE_ARTIST_ID,
            "artist_name": "RESCENE",
            "artist_type": "GROUP",
        }
    )
    for member in MEMBER_NAMES:
        result.artists.append(
            {
                "artist_id": artist_id_for_member(member),
                "artist_name": member,
                "artist_type": "PERSON",
            }
        )
    result.artist_external_identifiers.append(
        {
            "artist_id": RESCENE_ARTIST_ID,
            "source_system": "mediawiki",
            "external_id": f"en:{page_id}",
            "source_url": page_url,
        }
    )
    for member in MEMBER_NAMES:
        member_id = artist_id_for_member(member)
        result.artist_relationships.append(
            {
                "relationship_id": relationship_id(member_id, RESCENE_ARTIST_ID),
                "from_artist_id": member_id,
                "to_artist_id": RESCENE_ARTIST_ID,
                "relationship_type": "MEMBER_OF",
                "start_date": None,
                "end_date": None,
                "source_name": "English Wikipedia",
                "source_url": page_url,
            }
        )
    for release in releases:
        event_id = release_event_id(release["event_name"], release["release_date"])
        result.artist_events.append(
            {
                "event_id": event_id,
                "event_type": "RELEASE",
                "event_name": release["event_name"],
                "start_at": f"{release['release_date']}T00:00:00Z",
                "start_precision": "DATE",
                "end_at": None,
                "end_precision": None,
                "source_name": "English Wikipedia",
                "source_url": page_url,
            }
        )
        result.event_artists.append(
            {
                "event_id": event_id,
                "artist_id": RESCENE_ARTIST_ID,
                "participation_role": None,
            }
        )

    keyed_records = (
        ("artist", result.artists, lambda row: row["artist_id"]),
        (
            "artist_external_identifier",
            result.artist_external_identifiers,
            lambda row: "|".join(
                (row["artist_id"], row["source_system"], row["external_id"])
            ),
        ),
        (
            "artist_relationship",
            result.artist_relationships,
            lambda row: row["relationship_id"],
        ),
        ("artist_event", result.artist_events, lambda row: row["event_id"]),
        (
            "event_artist",
            result.event_artists,
            lambda row: f"{row['event_id']}|{row['artist_id']}",
        ),
    )
    for record_type, records, key_function in keyed_records:
        for record in records:
            result.lineage.append(
                _lineage(
                    record_type,
                    key_function(record),
                    "en",
                    page_id,
                    revision_id,
                    source_reference,
                )
            )
    return result


def latest_mediawiki_bronze(storage: Any) -> tuple[str, dict[str, Any]]:
    objects = storage.list_records(prefix=MEDIAWIKI_PREFIX)
    if not objects:
        raise MediaWikiTransformError("No English MediaWiki Bronze revisions found.")
    valid = [
        item
        for item in objects
        if isinstance(item[1], dict)
        and item[1].get("source") == "mediawiki"
        and item[1].get("edition") == "en"
        and isinstance(item[1].get("revision_id"), int)
    ]
    if not valid:
        raise MediaWikiTransformError("No valid English MediaWiki Bronze revisions found.")
    return max(valid, key=lambda item: item[1]["revision_id"])


def transform_latest_from_minio(storage: Any) -> MediaWikiSilverResult:
    source_reference, envelope = latest_mediawiki_bronze(storage)
    return transform_mediawiki_bronze(source_reference, envelope)
