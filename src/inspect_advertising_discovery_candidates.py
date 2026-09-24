"""Print persisted RESCENE KR discovery candidates without writing data."""

if __package__:
    from .advertising_candidate_reader import CandidateFilters, print_candidates, read_discovered_candidates
    from .mvp_config import RESCENE_ARTIST_ID
    from .silver_iceberg import build_spark_session
else:
    from advertising_candidate_reader import CandidateFilters, print_candidates, read_discovered_candidates
    from mvp_config import RESCENE_ARTIST_ID
    from silver_iceberg import build_spark_session


def main() -> int:
    spark = build_spark_session()
    try:
        rows = read_discovered_candidates(
            spark,
            CandidateFilters(
                discovered_for_artist_id=RESCENE_ARTIST_ID,
                market_code="KR",
            ),
        )
        print_candidates(rows)
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
