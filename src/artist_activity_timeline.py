"""Project supported canonical domain facts into an artist activity timeline."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
import json
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5


SOURCE_EVENT_TYPES = {
    "YOUTUBE": {"VIDEO_PUBLISHED"},
    "ARTIST_EVENT": None,
    "ADVERTISING": {
        "CAMPAIGN_ANNOUNCED",
        "CAMPAIGN_STARTED",
        "CAMPAIGN_ENDED",
        "OFFICIAL_EVIDENCE_PUBLISHED",
    },
}
PRECISIONS = {"TIMESTAMP", "DATE"}
TIME_SEMANTICS = {"EVENT_TIME", "PUBLICATION_TIME", "EFFECTIVE_TIME"}
FIXED_EVENT_SEMANTICS = {
    ("YOUTUBE", "VIDEO_PUBLISHED"): ("TIMESTAMP", "PUBLICATION_TIME"),
    ("ADVERTISING", "CAMPAIGN_ANNOUNCED"): ("TIMESTAMP", "EVENT_TIME"),
    ("ADVERTISING", "CAMPAIGN_STARTED"): ("DATE", "EFFECTIVE_TIME"),
    ("ADVERTISING", "CAMPAIGN_ENDED"): ("DATE", "EFFECTIVE_TIME"),
}


@dataclass
class ArtistActivityTimelineResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    event_evidence: list[dict[str, str]] = field(default_factory=list)


def timeline_event_id(
    artist_id: str,
    source_domain: str,
    source_entity_type: str,
    source_entity_id: str,
    event_type: str,
) -> str:
    """Return the stable identity of one artist-related source-domain fact."""
    identity = json.dumps(
        [artist_id, source_domain, source_entity_type, source_entity_id, event_type],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"timeline_event_{uuid5(NAMESPACE_URL, f'contents-lakehouse:timeline:{identity}').hex}"


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _utc_timestamp(value: Any, field: str) -> str:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _date_boundary(value: Any, field: str) -> str:
    text = _required_text(value, field)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO 8601 date.") from error
    return datetime.combine(parsed, time.min, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _record_key(value: Any) -> tuple[Any, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def validate_artist_activity_timeline(
    result: ArtistActivityTimelineResult, artist_ids: Iterable[str]
) -> None:
    """Validate the timeline constraints available inside one projection batch."""
    known_artists = set(artist_ids)
    event_ids: set[str] = set()
    for row in result.events:
        event_id = _required_text(row.get("timeline_event_id"), "timeline_event_id")
        if event_id in event_ids:
            raise ValueError("Duplicate timeline_event_id.")
        event_ids.add(event_id)
        if row.get("artist_id") not in known_artists:
            raise ValueError("Invalid timeline artist reference.")
        domain = row.get("source_domain")
        event_type = row.get("event_type")
        if domain not in SOURCE_EVENT_TYPES:
            raise ValueError("Unsupported timeline source_domain.")
        supported = SOURCE_EVENT_TYPES[domain]
        if supported is not None and event_type not in supported:
            raise ValueError("Unsupported source-domain/event-type combination.")
        if row.get("temporal_precision") not in PRECISIONS:
            raise ValueError("Unsupported temporal_precision.")
        if row.get("time_semantics") not in TIME_SEMANTICS:
            raise ValueError("Unsupported time_semantics.")
        expected_semantics = FIXED_EVENT_SEMANTICS.get((domain, event_type))
        if expected_semantics is not None and (
            row["temporal_precision"], row["time_semantics"]
        ) != expected_semantics:
            raise ValueError("Invalid precision or time semantics for event type.")
        if domain == "ARTIST_EVENT" and row["time_semantics"] != "EVENT_TIME":
            raise ValueError("Artist events require EVENT_TIME semantics.")
        if (
            (domain, event_type) == ("ADVERTISING", "OFFICIAL_EVIDENCE_PUBLISHED")
            and row["time_semantics"] != "PUBLICATION_TIME"
        ):
            raise ValueError("Official evidence publication requires PUBLICATION_TIME.")
        event_at = _utc_timestamp(row.get("event_at"), "event_at")
        if row["temporal_precision"] == "DATE" and not event_at.endswith("T00:00:00Z"):
            raise ValueError("DATE precision requires a UTC midnight boundary.")
        observed_at = row.get("observed_at")
        if observed_at is not None:
            _utc_timestamp(observed_at, "observed_at")
        expected_id = timeline_event_id(
            row["artist_id"],
            domain,
            _required_text(row.get("source_entity_type"), "source_entity_type"),
            _required_text(row.get("source_entity_id"), "source_entity_id"),
            _required_text(event_type, "event_type"),
        )
        if event_id != expected_id:
            raise ValueError("Invalid deterministic timeline_event_id.")

    evidence_keys: set[tuple[str, str]] = set()
    for row in result.event_evidence:
        key = (
            _required_text(row.get("timeline_event_id"), "timeline_event_id"),
            _required_text(row.get("source_evidence_id"), "source_evidence_id"),
        )
        if key in evidence_keys:
            raise ValueError("Duplicate timeline event evidence assignment.")
        evidence_keys.add(key)
        if key[0] not in event_ids:
            raise ValueError("Invalid timeline event evidence reference.")


def project_artist_activity_timeline(
    *,
    artist_ids: Iterable[str],
    youtube_channels: Iterable[dict[str, Any]] = (),
    youtube_videos: Iterable[dict[str, Any]] = (),
    video_metrics_snapshots: Iterable[dict[str, Any]] = (),
    youtube_lineage: Iterable[dict[str, Any]] = (),
    artist_events: Iterable[dict[str, Any]] = (),
    event_artists: Iterable[dict[str, Any]] = (),
    advertising_campaigns: Iterable[dict[str, Any]] = (),
    campaign_artists: Iterable[dict[str, Any]] = (),
    source_evidence: Iterable[dict[str, Any]] = (),
    canonical_field_evidence: Iterable[dict[str, Any]] = (),
) -> ArtistActivityTimelineResult:
    """Return a sorted, idempotent projection of explicit temporal facts only."""
    artists = set(artist_ids)
    channels = _unique_index(youtube_channels, "channel_id", "YouTube channel")
    observations: dict[str, list[str]] = {}
    for row in video_metrics_snapshots:
        observations.setdefault(row["video_id"], []).append(
            _utc_timestamp(row["observed_at"], "observed_at")
        )
    youtube_sources = {
        _record_key(row.get("record_key"))[0]: row.get("source_reference")
        for row in youtube_lineage
        if row.get("record_type") == "youtube_video" and row.get("record_key")
    }
    evidence = _unique_index(source_evidence, "source_evidence_id", "source evidence")
    selected_evidence: dict[tuple[str, str, str | None], set[str]] = {}
    for row in canonical_field_evidence:
        if row.get("is_selected") is False:
            continue
        evidence_id = row.get("source_evidence_id")
        if evidence_id not in evidence:
            raise ValueError("Invalid canonical field evidence reference.")
        selected_evidence.setdefault(
            (row["entity_type"], row["entity_id"], row.get("field_name")), set()
        ).add(evidence_id)

    result = ArtistActivityTimelineResult()
    keyed: dict[str, dict[str, Any]] = {}
    assignments: set[tuple[str, str]] = set()

    def add_event(
        *,
        artist_id: str,
        event_type: str,
        event_name: str,
        event_at: str,
        temporal_precision: str,
        time_semantics: str,
        observed_at: str | None,
        source_domain: str,
        source_entity_type: str,
        source_entity_id: str,
        source_reference: str | None,
        evidence_ids: Iterable[str] = (),
    ) -> None:
        event_id = timeline_event_id(
            artist_id, source_domain, source_entity_type, source_entity_id, event_type
        )
        row = {
            "timeline_event_id": event_id,
            "artist_id": artist_id,
            "event_type": event_type,
            "event_name": event_name,
            "event_at": event_at,
            "temporal_precision": temporal_precision,
            "time_semantics": time_semantics,
            "observed_at": observed_at,
            "source_domain": source_domain,
            "source_entity_type": source_entity_type,
            "source_entity_id": source_entity_id,
            "source_reference": source_reference,
        }
        current = keyed.get(event_id)
        if current is not None and current != row:
            raise ValueError("Conflicting duplicate logical timeline event.")
        keyed[event_id] = row
        for evidence_id in evidence_ids:
            if evidence_id not in evidence:
                raise ValueError("Invalid timeline source evidence reference.")
            assignments.add((event_id, evidence_id))

    for video in youtube_videos:
        channel = channels.get(video.get("channel_id"))
        if channel is None:
            raise ValueError("Invalid YouTube video channel reference.")
        observed = observations.get(video["video_id"], [])
        add_event(
            artist_id=channel["artist_id"],
            event_type="VIDEO_PUBLISHED",
            event_name=_required_text(video.get("title"), "title"),
            event_at=_utc_timestamp(video.get("published_at"), "published_at"),
            temporal_precision="TIMESTAMP",
            time_semantics="PUBLICATION_TIME",
            observed_at=min(observed) if observed else None,
            source_domain="YOUTUBE",
            source_entity_type="YOUTUBE_VIDEO",
            source_entity_id=video["video_id"],
            source_reference=youtube_sources.get(video["video_id"]),
        )

    events = _unique_index(artist_events, "event_id", "artist event")
    for link in event_artists:
        event = events.get(link.get("event_id"))
        if event is None:
            raise ValueError("Invalid event_artist event reference.")
        start_at = event.get("start_at")
        if start_at is None:
            continue
        precision = _required_text(
            event.get("start_precision"), "start_precision"
        ).upper()
        if event.get("end_at") is not None:
            end_at = _utc_timestamp(event["end_at"], "end_at")
            if _utc_timestamp(start_at, "start_at") > end_at:
                raise ValueError("Artist event start_at must not be after end_at.")
        if precision == "DATE":
            normalized = _utc_timestamp(start_at, "start_at")
        elif precision == "TIMESTAMP":
            normalized = _utc_timestamp(start_at, "start_at")
        else:
            raise ValueError("Artist event start precision must be DATE or TIMESTAMP.")
        add_event(
            artist_id=link["artist_id"],
            event_type=_required_text(event.get("event_type"), "event_type"),
            event_name=_required_text(event.get("event_name"), "event_name"),
            event_at=normalized,
            temporal_precision=precision,
            time_semantics="EVENT_TIME",
            observed_at=None,
            source_domain="ARTIST_EVENT",
            source_entity_type="ARTIST_EVENT",
            source_entity_id=event["event_id"],
            source_reference=event.get("source_url"),
        )

    campaigns = _unique_index(
        advertising_campaigns, "campaign_id", "advertising campaign"
    )
    for relationship in campaign_artists:
        campaign = campaigns.get(relationship.get("campaign_id"))
        if campaign is None:
            raise ValueError("Invalid campaign_artist campaign reference.")
        artist_id = relationship["artist_id"]
        relationship_id = relationship["campaign_artist_id"]
        campaign_id = campaign["campaign_id"]
        event_name = campaign.get("campaign_name") or relationship.get(
            "participation_role"
        ) or "Advertising campaign"
        if (
            campaign.get("campaign_start_date") is not None
            and campaign.get("campaign_end_date") is not None
            and date.fromisoformat(campaign["campaign_start_date"])
            > date.fromisoformat(campaign["campaign_end_date"])
        ):
            raise ValueError(
                "campaign_start_date must not be after campaign_end_date."
            )
        relationship_evidence = set()
        for (entity_type, entity_id, _field), values in selected_evidence.items():
            if (entity_type, entity_id) == ("CAMPAIGN_ARTIST", relationship_id):
                relationship_evidence.update(values)
        announced_at = campaign.get("announced_at")
        if announced_at is not None:
            announcement_evidence = selected_evidence.get(
                ("CAMPAIGN", campaign_id, "announced_at"), set()
            )
            add_event(
                artist_id=artist_id,
                event_type="CAMPAIGN_ANNOUNCED",
                event_name=event_name,
                event_at=_utc_timestamp(announced_at, "announced_at"),
                temporal_precision="TIMESTAMP",
                time_semantics="EVENT_TIME",
                observed_at=_earliest_observation(announcement_evidence, evidence),
                source_domain="ADVERTISING",
                source_entity_type="ADVERTISING_CAMPAIGN",
                source_entity_id=campaign_id,
                source_reference=None,
                evidence_ids=sorted(announcement_evidence),
            )
        for field_name, event_type in (
            ("campaign_start_date", "CAMPAIGN_STARTED"),
            ("campaign_end_date", "CAMPAIGN_ENDED"),
        ):
            value = campaign.get(field_name)
            if value is None:
                continue
            field_evidence = selected_evidence.get(
                ("CAMPAIGN", campaign_id, field_name), set()
            )
            add_event(
                artist_id=artist_id,
                event_type=event_type,
                event_name=event_name,
                event_at=_date_boundary(value, field_name),
                temporal_precision="DATE",
                time_semantics="EFFECTIVE_TIME",
                observed_at=_earliest_observation(field_evidence, evidence),
                source_domain="ADVERTISING",
                source_entity_type="ADVERTISING_CAMPAIGN",
                source_entity_id=campaign_id,
                source_reference=None,
                evidence_ids=sorted(field_evidence),
            )

        for evidence_id in sorted(relationship_evidence):
            item = evidence[evidence_id]
            if item.get("published_at") is None:
                continue
            published_at = _utc_timestamp(item["published_at"], "published_at")
            precision = "DATE" if published_at.endswith("T00:00:00Z") else "TIMESTAMP"
            add_event(
                artist_id=artist_id,
                event_type="OFFICIAL_EVIDENCE_PUBLISHED",
                event_name=event_name,
                event_at=published_at,
                temporal_precision=precision,
                time_semantics="PUBLICATION_TIME",
                observed_at=_utc_timestamp(item["collected_at"], "collected_at"),
                source_domain="ADVERTISING",
                source_entity_type="SOURCE_EVIDENCE",
                source_entity_id=evidence_id,
                source_reference=item.get("source_url"),
                evidence_ids=(evidence_id,),
            )

    result.events = sorted(
        keyed.values(), key=lambda row: (row["event_at"], row["timeline_event_id"])
    )
    result.event_evidence = [
        {"timeline_event_id": event_id, "source_evidence_id": evidence_id}
        for event_id, evidence_id in sorted(assignments)
    ]
    validate_artist_activity_timeline(result, artists)
    return result


def _earliest_observation(
    evidence_ids: Iterable[str], evidence: dict[str, dict[str, Any]]
) -> str | None:
    values = [
        _utc_timestamp(evidence[item]["collected_at"], "collected_at")
        for item in evidence_ids
        if evidence[item].get("collected_at") is not None
    ]
    return min(values) if values else None


def _unique_index(
    rows: Iterable[dict[str, Any]], key_field: str, label: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _required_text(row.get(key_field), key_field)
        if key in result:
            raise ValueError(f"Duplicate {label} key.")
        result[key] = row
    return result
