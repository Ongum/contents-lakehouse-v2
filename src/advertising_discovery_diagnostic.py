"""In-memory diagnostic evaluation for Artist-first discovery results."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

if __package__:
    from .advertising_discovery import candidate_id, normalize_discovery_url
    from .artist_advertising_watchlist import (
        ArtistWatchlistEntry,
        commercial_relationship_match,
        generate_discovery_queries,
    )
else:
    from advertising_discovery import candidate_id, normalize_discovery_url
    from artist_advertising_watchlist import (
        ArtistWatchlistEntry,
        commercial_relationship_match,
        generate_discovery_queries,
    )


@dataclass
class DiagnosticResult:
    title: str
    normalized_url: str
    discovered_for_artist_id: str
    snippet: str | None
    publication_date: str | None
    queries: list[str] = field(default_factory=list)
    matched_artist_alias: str | None = None
    matched_commercial_signal: str | None = None
    rejection_reason: str | None = None


def run_diagnostic(
    adapter: Any,
    watchlist: list[ArtistWatchlistEntry],
    query_templates: list[str],
    commercial_signals: dict[str, list[str]],
    results_per_query: int = 2,
    page_observer: Any | None = None,
) -> dict[str, Any]:
    entries = {entry.artist_id: entry for entry in watchlist}
    queries = generate_discovery_queries(watchlist, query_templates)
    unique: dict[str, DiagnosticResult] = {}
    total_results = 0
    duplicates = 0
    for query in queries:
        entry = entries[query.artist_id]
        if hasattr(adapter, "fetch_first_page_capture"):
            page = adapter.fetch_first_page_capture(query.query_text)
            if page_observer is not None:
                page_observer(query, page)
            search_results = page.results
        else:
            search_results = adapter.fetch_first_page(query.query_text)
        for result in search_results[:results_per_query]:
            total_results += 1
            normalized_url = normalize_discovery_url(result.url)
            identity = candidate_id(adapter.source_name, normalized_url)
            if identity in unique:
                duplicates += 1
                if query.query_text not in unique[identity].queries:
                    unique[identity].queries.append(query.query_text)
                continue
            combined_text = " ".join(
                value for value in (result.title, result.snippet) if value
            )
            match = commercial_relationship_match(
                entry, combined_text, commercial_signals
            )
            diagnostic = DiagnosticResult(
                title=result.title,
                normalized_url=normalized_url,
                discovered_for_artist_id=query.artist_id,
                snippet=result.snippet,
                publication_date=result.publication_date,
                queries=[query.query_text],
            )
            if match is None:
                diagnostic.rejection_reason = (
                    "No watched-artist commercial signal in title/snippet"
                )
            else:
                diagnostic.matched_artist_alias = match[0]
                diagnostic.matched_commercial_signal = match[1]
            unique[identity] = diagnostic
    accepted = [item for item in unique.values() if item.rejection_reason is None]
    rejected = [item for item in unique.values() if item.rejection_reason is not None]
    accepted_by_signal = Counter(
        item.matched_commercial_signal for item in accepted
    )
    return {
        "queries": queries,
        "accepted": accepted,
        "rejected": rejected,
        "total_results_inspected": total_results,
        "unique_results": len(unique),
        "accepted_candidates": len(accepted),
        "rejected_results": len(rejected),
        "duplicates": duplicates,
        "acceptance_rate": len(accepted) / len(unique) if unique else 0.0,
        "accepted_by_signal": dict(sorted(accepted_by_signal.items())),
    }
