"""Artist-first KR advertising discovery configuration and candidate filtering."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__:
    from .advertising_discovery import build_candidate
else:
    from advertising_discovery import build_candidate


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "advertising_discovery.json"
)
CANONICAL_DISCOVERY_SIGNALS = {
    "MODEL",
    "AMBASSADOR",
    "CAMPAIGN",
    "COLLABORATION",
    "ENDORSEMENT",
    "SPONSORSHIP",
}
CONSERVATIVE_COLLABORATION_PATTERNS = (
    re.compile(
        r"(?:와|과)\s*.{0,30}?(?:ai|브랜드|제품|서비스|플랫폼)\s*"
        r"경험(?:을)?\s*알린다",
        re.IGNORECASE,
    ),
)
SIGNAL_EXCLUSION_PATTERNS = {
    "AMBASSADOR": (
        re.compile(r"앰(?:배|버)서더\s*수상", re.IGNORECASE),
    ),
}


@dataclass(frozen=True)
class ArtistWatchlistEntry:
    artist_id: str
    canonical_artist_name: str
    korean_name: str | None
    english_name: str | None
    entity_type: str
    discovery_enabled: bool
    priority: int | None

    def discovery_names(self) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()
        for name in (self.korean_name, self.english_name, self.canonical_artist_name):
            if isinstance(name, str) and name.strip():
                normalized = name.strip()
                key = normalized.casefold()
                if key not in seen:
                    names.append(normalized)
                    seen.add(key)
        return tuple(names)


@dataclass(frozen=True)
class DiscoveryQuery:
    artist_id: str
    market_code: str
    query_text: str


def load_discovery_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("market_code") != "KR":
        raise ValueError("Artist advertising discovery market_code must be KR.")
    templates = config.get("query_templates")
    if not isinstance(templates, list) or not templates:
        raise ValueError("At least one discovery query template is required.")
    if any(not isinstance(item, str) or item.count("{artist}") != 1 for item in templates):
        raise ValueError("Every discovery query template must contain {artist} exactly once.")
    signals = config.get("commercial_signals")
    if not isinstance(signals, dict) or set(signals) != CANONICAL_DISCOVERY_SIGNALS:
        raise ValueError("Commercial signals must use the supported canonical names.")
    if any(
        not isinstance(variants, list)
        or not variants
        or any(not isinstance(item, str) or not item.strip() for item in variants)
        for variants in signals.values()
    ):
        raise ValueError("Every canonical commercial signal requires lexical variants.")
    if not isinstance(config.get("artists"), list):
        raise ValueError("Discovery artists must be a list.")
    return config


def resolve_watchlist(
    canonical_artists: list[dict[str, Any]], config: dict[str, Any]
) -> list[ArtistWatchlistEntry]:
    """Join discovery state to canonical artist rows by stable artist_id."""
    canonical = {row["artist_id"]: row for row in canonical_artists}
    entries = []
    seen = set()
    for item in config["artists"]:
        artist_id = item.get("artist_id")
        if artist_id in seen:
            raise ValueError(f"Duplicate watchlist artist_id: {artist_id!r}.")
        if artist_id not in canonical:
            raise ValueError(f"Unknown canonical watchlist artist_id: {artist_id!r}.")
        artist = canonical[artist_id]
        entity_type = artist.get("artist_type")
        if entity_type not in {"GROUP", "PERSON"}:
            raise ValueError(f"Unsupported canonical artist_type: {entity_type!r}.")
        enabled = item.get("discovery_enabled")
        if not isinstance(enabled, bool):
            raise ValueError("discovery_enabled must be boolean.")
        priority = item.get("priority")
        if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)):
            raise ValueError("priority must be an integer or null.")
        entries.append(
            ArtistWatchlistEntry(
                artist_id=artist_id,
                canonical_artist_name=artist["artist_name"],
                korean_name=item.get("korean_name"),
                english_name=item.get("english_name"),
                entity_type=entity_type,
                discovery_enabled=enabled,
                priority=priority,
            )
        )
        seen.add(artist_id)
    return entries


def generate_discovery_queries(
    watchlist: list[ArtistWatchlistEntry], query_templates: list[str]
) -> list[DiscoveryQuery]:
    if any(template.count("{artist}") != 1 for template in query_templates):
        raise ValueError("Every discovery query template must contain {artist} exactly once.")
    enabled = sorted(
        (entry for entry in watchlist if entry.discovery_enabled),
        key=lambda entry: (-(entry.priority or 0), entry.artist_id),
    )
    return [
        DiscoveryQuery(entry.artist_id, "KR", template.format(artist=name))
        for entry in enabled
        for name in entry.discovery_names()
        for template in query_templates
    ]


def has_commercial_relationship_signal(
    entry: ArtistWatchlistEntry,
    discovery_text: str,
    commercial_signals: dict[str, list[str]],
    proximity_characters: int = 80,
) -> bool:
    """Require an artist alias near an explicit commercial-intent phrase."""
    return commercial_relationship_match(
        entry, discovery_text, commercial_signals, proximity_characters
    ) is not None


def commercial_relationship_match(
    entry: ArtistWatchlistEntry,
    discovery_text: str,
    commercial_signals: dict[str, list[str]],
    proximity_characters: int = 80,
) -> tuple[str, str] | None:
    """Return the first configured alias/signal pair that passes the filter."""
    text = " ".join(discovery_text.casefold().split())

    def positions(needle: str) -> list[int]:
        found = []
        start = 0
        while True:
            position = text.find(needle.casefold(), start)
            if position < 0:
                return found
            found.append(position)
            start = position + max(1, len(needle))

    artist_positions = [
        (name, position)
        for name in entry.discovery_names()
        for position in positions(name)
    ]
    signal_positions: list[tuple[str, int]] = []
    for canonical_signal, variants in commercial_signals.items():
        if any(
            pattern.search(text)
            for pattern in SIGNAL_EXCLUSION_PATTERNS.get(canonical_signal, ())
        ):
            continue
        for variant in variants:
            # Only spaces inside configured expressions are optional. Text outside
            # those expressions is left untouched.
            expression = r"\s*".join(
                re.escape(part) for part in variant.casefold().split(" ")
            )
            signal_positions.extend(
                (canonical_signal, match.start())
                for match in re.finditer(expression, text, re.IGNORECASE)
            )
    signal_positions.extend(
        ("COLLABORATION", match.start())
        for pattern in CONSERVATIVE_COLLABORATION_PATTERNS
        for match in pattern.finditer(text)
    )
    for name, artist_position in artist_positions:
        for canonical_signal, signal_position in signal_positions:
            if abs(artist_position - signal_position) <= proximity_characters:
                return name, canonical_signal
    return None


def build_artist_discovery_candidate(
    entry: ArtistWatchlistEntry,
    *,
    discovery_text: str,
    commercial_signals: dict[str, list[str]],
    **candidate_fields: Any,
) -> dict[str, Any]:
    if not entry.discovery_enabled:
        raise ValueError("Discovery candidate artist is not enabled.")
    if not has_commercial_relationship_signal(
        entry, discovery_text, commercial_signals
    ):
        raise ValueError("Candidate lacks a plausible watched-artist commercial signal.")
    return build_candidate(
        discovered_for_artist_id=entry.artist_id,
        **candidate_fields,
    )
