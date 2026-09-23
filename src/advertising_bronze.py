"""Compatibility facade for the split advertising Bronze collector modules."""

if __package__:
    from .advertising_bronze_storage import AdvertisingBronzeStorage
    from .advertising_collection import (
        ADVERTISING_FIELDS,
        COLLECTOR_VERSION,
        SENSITIVE_NORMALIZED_NAMES,
        AdvertisingStorageConflict,
        CollectionResult,
        CollectionStatus,
        FetchedDocument,
        MalformedDocumentError,
        SourceAdapter,
        SourceConfig,
        SourceFetchError,
        build_bronze_record,
        canonicalize_content,
        collect_source,
        content_hash,
        is_sensitive_name,
        safe_url,
        sanitize_metadata,
        utc_now,
        validate_source_config,
    )
    from .http_document_adapter import (
        RETRYABLE_HTTP_STATUS,
        USER_AGENT,
        HttpDocumentAdapter,
    )
else:
    from advertising_bronze_storage import AdvertisingBronzeStorage
    from advertising_collection import (
        ADVERTISING_FIELDS,
        COLLECTOR_VERSION,
        SENSITIVE_NORMALIZED_NAMES,
        AdvertisingStorageConflict,
        CollectionResult,
        CollectionStatus,
        FetchedDocument,
        MalformedDocumentError,
        SourceAdapter,
        SourceConfig,
        SourceFetchError,
        build_bronze_record,
        canonicalize_content,
        collect_source,
        content_hash,
        is_sensitive_name,
        safe_url,
        sanitize_metadata,
        utc_now,
        validate_source_config,
    )
    from http_document_adapter import (
        RETRYABLE_HTTP_STATUS,
        USER_AGENT,
        HttpDocumentAdapter,
    )

_safe_url = safe_url
_validate_config = validate_source_config
