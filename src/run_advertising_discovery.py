"""Run Artist-first KR advertising discovery in persistence or dry-run mode."""

import argparse
import os
from datetime import datetime, timezone

if __package__:
    from .advertising_discovery_bronze import AdvertisingDiscoveryBronzeStorage
    from .advertising_discovery_pipeline import execute_discovery
    from .advertising_discovery_search import GoogleNewsKrRssAdapter
    from .advertising_discovery_staging import persist_discovered_candidates
    from .artist_advertising_watchlist import load_discovery_config, resolve_watchlist
    from .silver_iceberg import build_spark_session
else:
    from advertising_discovery_bronze import AdvertisingDiscoveryBronzeStorage
    from advertising_discovery_pipeline import execute_discovery
    from advertising_discovery_search import GoogleNewsKrRssAdapter
    from advertising_discovery_staging import persist_discovered_candidates
    from artist_advertising_watchlist import load_discovery_config, resolve_watchlist
    from silver_iceberg import build_spark_session


def _arguments(values: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-results-per-query", type=int, default=2, choices=range(1, 11))
    parser.add_argument("--request-timeout", type=float, default=10.0)
    parser.add_argument("--max-attempts", type=int, default=2, choices=range(1, 4))
    arguments = parser.parse_args(values)
    if not 1.0 <= arguments.request_timeout <= 30.0:
        parser.error("--request-timeout must be between 1 and 30 seconds")
    return arguments


def _canonical_artists(spark, artist_ids: list[str]) -> list[dict[str, str]]:
    catalog = os.environ.get("ICEBERG_CATALOG", "lakehouse")
    namespace = os.environ.get("SILVER_NAMESPACE", "silver")
    artists = spark.table(f"{catalog}.{namespace}.artist")
    rows = (
        artists.filter(artists.artist_id.isin(artist_ids))
        .select("artist_id", "artist_name", "artist_type")
        .collect()
    )
    return [row.asDict() for row in rows]


def main(values: list[str] | None = None) -> int:
    arguments = _arguments(values)
    config = load_discovery_config()
    spark = build_spark_session()
    try:
        artist_ids = [item["artist_id"] for item in config["artists"]]
        watchlist = resolve_watchlist(_canonical_artists(spark, artist_ids), config)
        adapter = GoogleNewsKrRssAdapter(
            timeout_seconds=arguments.request_timeout,
            max_attempts=arguments.max_attempts,
        )
        bronze_storage = None
        candidate_persister = None
        if not arguments.dry_run:
            bronze_storage = AdvertisingDiscoveryBronzeStorage.from_environment()
            bronze_storage.ensure_bucket()
            candidate_persister = lambda rows: persist_discovered_candidates(spark, rows)
        report = execute_discovery(
            adapter=adapter,
            watchlist=watchlist,
            query_templates=config["query_templates"],
            commercial_signals=config["commercial_signals"],
            discovered_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            max_results_per_query=arguments.max_results_per_query,
            dry_run=arguments.dry_run,
            bronze_storage=bronze_storage,
            candidate_persister=candidate_persister,
        )
    finally:
        spark.stop()

    for key in (
        "artists_processed",
        "queries_executed",
        "results_inspected",
        "accepted_candidates",
        "rejected_results",
        "duplicates",
        "bronze_objects_created",
        "candidate_rows_inserted",
        "candidate_rows_already_existing",
    ):
        print(f"{key}: {report[key]}")
    print(f"run_duration: {report['run_duration']:.3f}s")
    print(f"mode: {'dry-run' if arguments.dry_run else 'persistence'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
