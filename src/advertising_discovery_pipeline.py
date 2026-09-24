"""Shared dry-run and persistence flow for Artist-first KR discovery."""

import re
import time
from typing import Any, Callable

if __package__:
    from .advertising_discovery import build_candidate, deduplicate_candidates
    from .advertising_discovery_bronze import build_discovery_record
    from .advertising_discovery_diagnostic import run_diagnostic
    from .advertising_discovery_staging import CandidatePersistenceResult
else:
    from advertising_discovery import build_candidate, deduplicate_candidates
    from advertising_discovery_bronze import build_discovery_record
    from advertising_discovery_diagnostic import run_diagnostic
    from advertising_discovery_staging import CandidatePersistenceResult


def _provisional_advertiser_text(title: str) -> str:
    """Preserve a conservative title prefix without resolving an entity."""
    prefix = re.split(r"[,，:：]", title, maxsplit=1)[0].strip(" \"'‘’“”")
    return prefix or title


def execute_discovery(
    *,
    adapter: Any,
    watchlist: list[Any],
    query_templates: list[str],
    commercial_signals: dict[str, list[str]],
    discovered_at: str,
    max_results_per_query: int,
    dry_run: bool,
    bronze_storage: Any | None = None,
    candidate_persister: Callable[[list[dict[str, Any]]], Any] | None = None,
) -> dict[str, Any]:
    if not 1 <= max_results_per_query <= 10:
        raise ValueError("max_results_per_query must be between 1 and 10.")
    if not dry_run and (bronze_storage is None or candidate_persister is None):
        raise ValueError("Normal discovery requires Bronze and staging persistence.")

    started = time.monotonic()
    bronze_objects_created = 0

    def capture_page(query: Any, page: Any) -> None:
        nonlocal bronze_objects_created
        if dry_run:
            return
        record = build_discovery_record(
            discovery_source=adapter.source_name,
            query=query.query_text,
            source_url=page.search_url,
            discovered_at=discovered_at,
            raw_content=page.raw_content,
            request_metadata=page.request_metadata,
        )
        _, created = bronze_storage.write_capture(record)
        bronze_objects_created += int(created)

    report = run_diagnostic(
        adapter,
        watchlist,
        query_templates,
        commercial_signals,
        results_per_query=max_results_per_query,
        page_observer=capture_page,
    )
    candidates = deduplicate_candidates(
        [
            build_candidate(
                discovered_at=discovered_at,
                discovery_source=adapter.source_name,
                source_url=item.normalized_url,
                advertiser_brand_text=_provisional_advertiser_text(item.title),
                product_text=None,
                campaign_text=item.title,
                artist_model_text=item.matched_artist_alias,
                publication_date=item.publication_date,
                market_code="KR",
                discovered_for_artist_id=item.discovered_for_artist_id,
                discovery_signal=item.matched_commercial_signal,
            )
            for item in report["accepted"]
        ]
    )
    persistence = CandidatePersistenceResult(0, 0)
    if not dry_run:
        persistence = candidate_persister(candidates)

    report.update(
        {
            "artists_processed": sum(
                1 for entry in watchlist if entry.discovery_enabled
            ),
            "queries_executed": len(report["queries"]),
            "results_inspected": report["total_results_inspected"],
            "bronze_objects_created": bronze_objects_created,
            "candidate_rows_inserted": persistence.inserted,
            "candidate_rows_already_existing": persistence.already_existing,
            "run_duration": time.monotonic() - started,
            "candidates": candidates,
        }
    )
    return report
