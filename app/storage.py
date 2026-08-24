from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from minio import Minio


@lru_cache
def get_minio() -> Minio:
    from minio import Minio

    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def is_minio_error(error: BaseException) -> bool:
    from minio.error import S3Error

    return isinstance(error, S3Error)


def ensure_bucket() -> None:
    settings = get_settings()
    client = get_minio()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
