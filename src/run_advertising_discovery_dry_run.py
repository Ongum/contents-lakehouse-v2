"""Compatibility wrapper for the read-only advertising discovery mode."""

if __package__:
    from .run_advertising_discovery import main as discovery_main
else:
    from run_advertising_discovery import main as discovery_main


def main() -> int:
    return discovery_main(["--dry-run"])


if __name__ == "__main__":
    raise SystemExit(main())
