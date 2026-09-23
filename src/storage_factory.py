"""Select the Bronze object store without changing source collectors."""

import os
from typing import Any

if __package__:
    from .bronze_storage import BronzeStorageError
    from .gcs_storage import GCSClientAdapter, GCSStorageError
else:
    from bronze_storage import BronzeStorageError
    from gcs_storage import GCSClientAdapter, GCSStorageError


def bronze_storage_from_environment(storage_class: type[Any]) -> Any:
    backend = os.environ.get("BRONZE_STORAGE_BACKEND", "minio").strip().lower()
    if backend == "minio":
        return storage_class.from_environment()
    if backend == "gcs":
        try:
            client, bucket = GCSClientAdapter.from_environment()
        except GCSStorageError as error:
            raise BronzeStorageError(str(error)) from error
        return storage_class(client, bucket)
    raise BronzeStorageError(
        "BRONZE_STORAGE_BACKEND must be either 'minio' or 'gcs'."
    )
