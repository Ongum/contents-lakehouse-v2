"""Verify real Narangd HTTP collection, MinIO persistence, and change detection."""

from pathlib import Path

from advertising_bronze_storage import AdvertisingBronzeStorage
from advertising_collection import (
    CollectionStatus,
    collect_source,
    content_hash,
)
from http_document_adapter import HttpDocumentAdapter
from advertising_sources import NARANGD_SOURCE, narangd_identity_content
from bronze_storage import BronzeStorageError
from youtube_connectivity import load_local_env


def main() -> int:
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    storage = AdvertisingBronzeStorage.from_environment()
    storage.ensure_bucket()
    adapter = HttpDocumentAdapter(identity_canonicalizer=narangd_identity_content)

    first = collect_source(NARANGD_SOURCE, adapter, storage)
    if first.status not in {CollectionStatus.SUCCESS, CollectionStatus.UNCHANGED}:
        raise BronzeStorageError(
            f"First collection failed: {first.status.value}: {first.error_message}"
        )
    stored = storage.read_record(first.object_key)
    if "리센느" not in stored.get("raw_content", "") or "나랑드" not in stored.get(
        "raw_content", ""
    ):
        raise BronzeStorageError(
            "Stored official source does not contain the expected RESCENE/Narangd terms."
        )
    if content_hash(stored.get("raw_content", "")) != stored.get(
        "raw_content_text_hash"
    ):
        raise BronzeStorageError("Stored Narangd raw content verification failed.")

    second = collect_source(NARANGD_SOURCE, adapter, storage)
    if second.status != CollectionStatus.UNCHANGED:
        raise BronzeStorageError(
            "Repeated Narangd collection did not produce UNCHANGED: "
            f"{second.status.value}."
        )
    if first.object_key != second.object_key:
        raise BronzeStorageError("Repeated Narangd collection changed object key.")

    print("Advertising Bronze verification succeeded.")
    print(f"First result: {first.status.value}")
    print(f"Second result: {second.status.value}")
    print(f"Content hash: {second.content_hash}")
    print(f"Object key: {second.object_key}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BronzeStorageError as error:
        raise SystemExit(f"Error: {error}") from error
