"""Read-only selection and display of persisted discovery candidates."""

from dataclasses import dataclass
from typing import Any

if __package__:
    from .advertising_discovery_staging import _table_name
else:
    from advertising_discovery_staging import _table_name


@dataclass(frozen=True)
class CandidateFilters:
    candidate_id: str | None = None
    discovered_for_artist_id: str | None = None
    market_code: str | None = None


def _literal(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Candidate filter values must be non-empty strings.")
    return "'" + value.replace("'", "''") + "'"


def read_discovered_candidates(
    spark: Any, filters: CandidateFilters = CandidateFilters()
) -> list[dict[str, Any]]:
    """Select DISCOVERED rows without creating or changing any table."""
    table_name = _table_name()
    columns = set(spark.table(table_name).columns)
    signal = (
        "discovery_signal" if "discovery_signal" in columns else "CAST(NULL AS STRING) AS discovery_signal"
    )
    predicates = ["evidence_status = 'DISCOVERED'"]
    for column, value in (
        ("candidate_id", filters.candidate_id),
        ("discovered_for_artist_id", filters.discovered_for_artist_id),
        ("market_code", filters.market_code),
    ):
        if value is not None:
            predicates.append(f"{column} = {_literal(value)}")
    query = (
        "SELECT candidate_id, campaign_text, source_url, "
        f"{signal}, discovered_at FROM {table_name} WHERE "
        + " AND ".join(predicates)
        + " ORDER BY discovered_at, candidate_id"
    )
    return [row.asDict(recursive=True) for row in spark.sql(query).collect()]


def print_candidates(rows: list[dict[str, Any]]) -> None:
    print(f"discovered_candidates: {len(rows)}")
    for row in rows:
        print(f"candidate_id: {row['candidate_id']}")
        print(f"title/campaign_text: {row.get('campaign_text') or ''}")
        print(f"source_url: {row['source_url']}")
        print(f"canonical_discovery_signal: {row.get('discovery_signal') or 'UNAVAILABLE'}")
        print(f"discovered_at: {row['discovered_at']}")
        print()
