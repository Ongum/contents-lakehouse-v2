"""Fetch the latest English Rescene revision and persist it to Bronze."""

import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__:
    from .bronze_storage import BronzeStorage, BronzeStorageError
    from .youtube_connectivity import load_local_env
else:
    from bronze_storage import BronzeStorage, BronzeStorageError
    from youtube_connectivity import load_local_env


MEDIAWIKI_API_URL = "https://en.wikipedia.org/w/api.php"
MEDIAWIKI_EDITION = "en"
MEDIAWIKI_PAGE_TITLE = "Rescene"
USER_AGENT = "ContentsLakehouseMVP/1.0 (MediaWiki Bronze ingestion)"

MEDIAWIKI_BRONZE_FIELDS = {
    "source",
    "edition",
    "page_id",
    "canonical_title",
    "revision_id",
    "parent_revision_id",
    "revision_timestamp",
    "ingested_at",
    "raw_wikitext",
}


class MediaWikiError(Exception):
    """Raised when the MediaWiki response cannot be fetched or parsed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_latest_revision() -> dict[str, Any]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "redirects": 1,
        "prop": "revisions",
        "rvlimit": 1,
        "rvprop": "ids|timestamp|content",
        "rvslots": "main",
        "titles": MEDIAWIKI_PAGE_TITLE,
    }
    request = Request(
        f"{MEDIAWIKI_API_URL}?{urlencode(params)}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise MediaWikiError(
            f"MediaWiki API request failed with HTTP {error.code}."
        ) from error
    except URLError as error:
        raise MediaWikiError(
            f"MediaWiki API request failed due to a network error: {error.reason}"
        ) from error
    except (json.JSONDecodeError, OSError) as error:
        raise MediaWikiError("MediaWiki API returned an unreadable response.") from error

    if not isinstance(payload, dict):
        raise MediaWikiError("MediaWiki API returned an invalid response.")
    return payload


def _required_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MediaWikiError(f"MediaWiki response has an invalid {field}.")
    return value


def _utc_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise MediaWikiError(f"MediaWiki response has an invalid {field}.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MediaWikiError(f"MediaWiki response has an invalid {field}.") from error
    if parsed.tzinfo is None:
        raise MediaWikiError(f"MediaWiki response {field} must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_latest_revision(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        pages = payload["query"]["pages"]
        page = pages[0]
        revisions = page["revisions"]
        revision = revisions[0]
        main_slot = revision["slots"]["main"]
    except (KeyError, IndexError, TypeError) as error:
        raise MediaWikiError(
            "MediaWiki response is missing page or revision data."
        ) from error

    if page.get("missing") is True:
        raise MediaWikiError(f'MediaWiki page "{MEDIAWIKI_PAGE_TITLE}" was not found.')
    canonical_title = page.get("title")
    if not isinstance(canonical_title, str) or not canonical_title:
        raise MediaWikiError("MediaWiki response has an invalid canonical title.")
    raw_wikitext = main_slot.get("content", main_slot.get("*"))
    if not isinstance(raw_wikitext, str):
        raise MediaWikiError("MediaWiki response is missing raw wikitext.")

    parent_revision_id = revision.get("parentid")
    if parent_revision_id in (None, 0):
        parent_revision_id = None
    else:
        parent_revision_id = _required_integer(
            parent_revision_id, "parent revision ID"
        )

    return {
        "page_id": _required_integer(page.get("pageid"), "page ID"),
        "canonical_title": canonical_title,
        "revision_id": _required_integer(revision.get("revid"), "revision ID"),
        "parent_revision_id": parent_revision_id,
        "revision_timestamp": _utc_timestamp(
            revision.get("timestamp"), "revision timestamp"
        ),
        "raw_wikitext": raw_wikitext,
    }


def build_bronze_record(
    revision: dict[str, Any], ingested_at: str | None = None
) -> dict[str, Any]:
    return {
        "source": "mediawiki",
        "edition": MEDIAWIKI_EDITION,
        "page_id": revision["page_id"],
        "canonical_title": revision["canonical_title"],
        "revision_id": revision["revision_id"],
        "parent_revision_id": revision["parent_revision_id"],
        "revision_timestamp": revision["revision_timestamp"],
        "ingested_at": ingested_at or utc_now(),
        "raw_wikitext": deepcopy(revision["raw_wikitext"]),
    }


class MediaWikiBronzeStorage(BronzeStorage):
    """Store one immutable object for each MediaWiki page revision."""

    @staticmethod
    def serialize_record(record: dict[str, Any]) -> bytes:
        missing = MEDIAWIKI_BRONZE_FIELDS - record.keys()
        if missing:
            raise BronzeStorageError(
                "MediaWiki Bronze record is missing fields: "
                f"{', '.join(sorted(missing))}."
            )
        if record["source"] != "mediawiki" or record["edition"] != "en":
            raise BronzeStorageError("Invalid MediaWiki Bronze source or edition.")
        if not isinstance(record["raw_wikitext"], str):
            raise BronzeStorageError("MediaWiki raw_wikitext must be a string.")
        try:
            return json.dumps(
                record, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise BronzeStorageError(
                "MediaWiki Bronze record is not JSON serializable."
            ) from error

    @staticmethod
    def object_name(record: dict[str, Any]) -> str:
        page_id = record["page_id"]
        revision_id = record["revision_id"]
        if (
            not isinstance(page_id, int)
            or isinstance(page_id, bool)
            or page_id <= 0
            or not isinstance(revision_id, int)
            or isinstance(revision_id, bool)
            or revision_id <= 0
        ):
            raise BronzeStorageError("Invalid MediaWiki page or revision ID.")
        return (
            "bronze/mediawiki/en/"
            f"page_id={page_id}/revision_id={revision_id}/page.json"
        )

    def write_record(self, record: dict[str, Any]) -> tuple[str, bool]:
        content = self.serialize_record(record)
        object_name = self.object_name(record)

        try:
            existing_content = self._read_bytes(object_name)
        except Exception as error:
            if not self._is_missing_object(error):
                raise BronzeStorageError(
                    f"Unable to check MediaWiki Bronze object {object_name}."
                ) from error
        else:
            try:
                existing = json.loads(existing_content)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise BronzeStorageError(
                    f"Invalid existing MediaWiki Bronze object {object_name}."
                ) from error
            identity = ("source", "edition", "page_id", "revision_id")
            if all(existing.get(field) == record[field] for field in identity):
                return object_name, False
            raise BronzeStorageError(
                f"MediaWiki Bronze object has conflicting identity: {object_name}."
            )

        try:
            self.client.put_object(
                self.bucket,
                object_name,
                BytesIO(content),
                len(content),
                content_type="application/json",
            )
        except Exception as error:
            raise BronzeStorageError(
                f"Unable to write MediaWiki Bronze object {object_name}."
            ) from error
        return object_name, True


def ingest_latest_revision(
    storage: MediaWikiBronzeStorage,
) -> tuple[str, bool, dict[str, Any]]:
    revision = parse_latest_revision(fetch_latest_revision())
    record = build_bronze_record(revision)
    object_name, created = storage.write_record(record)
    return object_name, created, record


def main() -> int:
    load_local_env(Path(__file__).resolve().parents[1] / ".env")
    try:
        storage = MediaWikiBronzeStorage.from_environment()
        storage.ensure_bucket()
        object_name, created, record = ingest_latest_revision(storage)
    except (MediaWikiError, BronzeStorageError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    outcome = "stored" if created else "already present"
    print(f"MediaWiki Bronze revision {outcome}.")
    print(f"Page: {record['canonical_title']} ({record['page_id']})")
    print(f"Revision: {record['revision_id']}")
    print(f"Revision timestamp: {record['revision_timestamp']}")
    print(f"Object: {object_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
