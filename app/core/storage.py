from __future__ import annotations

import logging
from datetime import timedelta
from io import BytesIO
from typing import NoReturn

import anyio
from minio import Minio
from minio.commonconfig import CopySource
from minio.error import S3Error

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)


def _get_minio_client_sync() -> Minio:
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def _raise_storage_unavailable(operation: str, exc: Exception) -> NoReturn:
    logger.exception("Object storage operation failed", extra={"event": operation})
    raise ServiceUnavailableError(
        code="STORAGE_UNAVAILABLE",
        message="Object storage is temporarily unavailable",
    ) from exc


async def build_presigned_get_url(
    *,
    bucket_name: str,
    object_name: str,
) -> str:
    def _op() -> str:
        try:
            client = _get_minio_client_sync()
            url = client.presigned_get_object(
                bucket_name=bucket_name,
                object_name=object_name,
                expires=timedelta(seconds=settings.presigned_download_expire_seconds),
            )
            return str(url)
        except Exception as exc:
            _raise_storage_unavailable("presigned_get", exc)

    return await anyio.to_thread.run_sync(_op)


async def build_presigned_put_url(
    *,
    bucket_name: str,
    object_name: str,
) -> str:
    def _op() -> str:
        try:
            client = _get_minio_client_sync()
            url = client.presigned_put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                expires=timedelta(seconds=settings.presigned_upload_expire_seconds),
            )
            return str(url)
        except Exception as exc:
            _raise_storage_unavailable("presigned_put", exc)

    return await anyio.to_thread.run_sync(_op)


async def object_exists(
    *,
    bucket_name: str,
    object_name: str,
) -> bool:
    def _op() -> bool:
        client = _get_minio_client_sync()
        try:
            client.stat_object(bucket_name, object_name)
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            _raise_storage_unavailable("stat_object", exc)
        except Exception as exc:
            _raise_storage_unavailable("stat_object", exc)

    return await anyio.to_thread.run_sync(_op)


async def move_object(
    *,
    src_bucket_name: str,
    src_object_name: str,
    dst_bucket_name: str,
    dst_object_name: str,
) -> None:
    def _op() -> None:
        try:
            client = _get_minio_client_sync()

            if (
                src_bucket_name == dst_bucket_name
                and src_object_name == dst_object_name
            ):
                return

            client.copy_object(
                bucket_name=dst_bucket_name,
                object_name=dst_object_name,
                source=CopySource(src_bucket_name, src_object_name),
            )
            client.remove_object(src_bucket_name, src_object_name)
        except Exception as exc:
            _raise_storage_unavailable("move_object", exc)

    await anyio.to_thread.run_sync(_op)


async def delete_object_if_exists(
    *,
    bucket_name: str,
    object_name: str,
) -> bool:
    def _op() -> bool:
        client = _get_minio_client_sync()
        try:
            client.stat_object(bucket_name, object_name)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            _raise_storage_unavailable("delete_object_if_exists", exc)
        except Exception as exc:
            _raise_storage_unavailable("delete_object_if_exists", exc)

        try:
            client.remove_object(bucket_name, object_name)
            return True
        except Exception as exc:
            _raise_storage_unavailable("remove_object", exc)

    return await anyio.to_thread.run_sync(_op)


async def bucket_exists(bucket_name: str) -> bool:
    def _op() -> bool:
        try:
            client = _get_minio_client_sync()
            result = client.bucket_exists(bucket_name)
            return bool(result)
        except Exception as exc:
            _raise_storage_unavailable("bucket_exists", exc)

    return await anyio.to_thread.run_sync(_op)


async def upload_bytes(
    *,
    bucket_name: str,
    object_name: str,
    data: bytes,
    content_type: str | None = None,
) -> None:
    def _op() -> None:
        try:
            client = _get_minio_client_sync()
            client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        except Exception as exc:
            _raise_storage_unavailable("put_object", exc)

    await anyio.to_thread.run_sync(_op)
