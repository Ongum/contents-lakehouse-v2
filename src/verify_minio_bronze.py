"""Write, read, verify, and remove one isolated Bronze test object."""

from pathlib import Path
from uuid import uuid4

if __package__:
    from .bronze_storage import BronzeStorage, BronzeStorageError
    from .youtube_connectivity import BronzeCapture, load_local_env
else:
    from bronze_storage import BronzeStorage, BronzeStorageError
    from youtube_connectivity import BronzeCapture, load_local_env


def main() -> int:
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    storage = BronzeStorage.from_environment()
    storage.ensure_bucket()
    capture = BronzeCapture(
        run_id=f"verification-{uuid4()}",
        observed_at="2026-09-22T00:00:00Z",
    )
    capture.add(
        "channels",
        {"part": "snippet", "verification": "true"},
        {"items": [{"id": "verification-only"}]},
    )
    expected = capture.records[0]
    object_name = storage.write_record(expected)

    try:
        actual = storage.read_record(object_name)
        if actual != expected:
            raise BronzeStorageError("Stored verification object did not round-trip.")
        print(f"MinIO Bronze verification succeeded: {object_name}")
    finally:
        storage.client.remove_object(storage.bucket, object_name)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BronzeStorageError as error:
        raise SystemExit(f"Error: {error}") from error
