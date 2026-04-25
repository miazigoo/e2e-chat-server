import hashlib
import hmac
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.push import build_app_update_push_payload, send_push_data_message
from app.core.realtime import realtime_hub
from app.core.storage import build_presigned_get_url, upload_bytes
from app.repositories.app_releases import AppReleasesRepository
from app.repositories.devices import DevicesRepository
from app.schemas.app_releases import ApkUploadResponseData, LatestAppReleaseResponseData

app_releases_repo = AppReleasesRepository()
devices_repo = DevicesRepository()

ANDROID_PLATFORM = "android"


def _validate_apk_upload_token(token: str | None) -> None:
    if not settings.apk_upload_token:
        raise ForbiddenError(
            code="APK_UPLOAD_DISABLED",
            message="APK upload token is not configured",
        )
    if not token or not hmac.compare_digest(token, settings.apk_upload_token):
        raise ForbiddenError(
            code="INVALID_APK_UPLOAD_TOKEN",
            message="APK upload token is invalid",
        )


async def upload_android_apk_release(
    session: AsyncSession,
    *,
    upload_token: str | None,
    version_name: str,
    version_code: int,
    changelog: str | None,
    file: UploadFile,
) -> ApkUploadResponseData:
    _validate_apk_upload_token(upload_token)

    normalized_version_name = version_name.strip()
    if not normalized_version_name:
        raise BadRequestError(
            code="INVALID_VERSION_NAME",
            message="version_name cannot be blank",
        )

    file_name = file.filename or "app-release.apk"
    if Path(file_name).suffix.lower() != ".apk":
        raise BadRequestError(
            code="INVALID_APK_FILE",
            message="Only .apk files are accepted",
        )

    content_type = file.content_type or "application/vnd.android.package-archive"
    data = await file.read()
    if not data:
        raise BadRequestError(code="EMPTY_APK_FILE", message="APK file is empty")
    if len(data) > settings.apk_max_bytes:
        raise BadRequestError(
            code="APK_TOO_LARGE",
            message="APK exceeds configured size limit",
        )

    sha256 = hashlib.sha256(data).hexdigest()
    storage_key = f"releases/android/{version_code}/{uuid4().hex}.apk"

    await upload_bytes(
        bucket_name=settings.minio_bucket_assets,
        object_name=storage_key,
        data=data,
        content_type=content_type,
    )

    await app_releases_repo.deactivate_platform_releases(
        session,
        platform=ANDROID_PLATFORM,
    )
    release = await app_releases_repo.create_release(
        session,
        platform=ANDROID_PLATFORM,
        version_name=normalized_version_name,
        version_code=version_code,
        file_name=file_name,
        bucket_name=settings.minio_bucket_assets,
        storage_key=storage_key,
        content_type=content_type,
        file_size=len(data),
        sha256=sha256,
        changelog=(changelog.strip() if changelog and changelog.strip() else None),
    )

    devices = await devices_repo.list_active_with_fcm(session)
    await session.commit()

    notified_devices = 0
    realtime_payload = {
        "type": "app_update_available",
        "platform": ANDROID_PLATFORM,
        "version_name": release.version_name,
        "version_code": release.version_code,
        "uploaded_at": release.created_at.isoformat(),
    }
    push_payload = build_app_update_push_payload(
        version_name=release.version_name,
        version_code=release.version_code,
    )

    for device in devices:
        await realtime_hub.publish_user_event(device.user_id, realtime_payload)
        if send_push_data_message(token=device.fcm_token or "", data=push_payload):
            notified_devices += 1

    return ApkUploadResponseData(
        platform=release.platform,
        version_name=release.version_name,
        version_code=release.version_code,
        file_name=release.file_name,
        file_size=release.file_size,
        sha256=release.sha256,
        uploaded_at=release.created_at,
        notified_devices=notified_devices,
    )


async def get_latest_android_apk_release(
    session: AsyncSession,
) -> LatestAppReleaseResponseData:
    release = await app_releases_repo.get_active_for_platform(
        session,
        platform=ANDROID_PLATFORM,
    )
    if release is None:
        raise NotFoundError(
            code="APK_RELEASE_NOT_FOUND",
            message="No active APK release found",
        )

    download_url = await build_presigned_get_url(
        bucket_name=release.bucket_name,
        object_name=release.storage_key,
    )
    return LatestAppReleaseResponseData(
        platform=release.platform,
        version_name=release.version_name,
        version_code=release.version_code,
        file_name=release.file_name,
        file_size=release.file_size,
        sha256=release.sha256,
        changelog=release.changelog,
        content_type=release.content_type,
        uploaded_at=release.created_at,
        download_url=download_url,
        download_url_expires_in=settings.presigned_download_expire_seconds,
    )
