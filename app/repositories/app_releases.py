from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_release import AppRelease


class AppReleasesRepository:
    async def get_active_for_platform(
        self,
        session: AsyncSession,
        *,
        platform: str,
    ) -> AppRelease | None:
        result = await session.execute(
            select(AppRelease)
            .where(
                AppRelease.platform == platform,
                AppRelease.is_active.is_(True),
            )
            .order_by(AppRelease.version_code.desc(), AppRelease.id.desc())
        )
        return result.scalars().first()

    async def create_release(
        self,
        session: AsyncSession,
        *,
        platform: str,
        version_name: str,
        version_code: int,
        file_name: str,
        bucket_name: str,
        storage_key: str,
        content_type: str,
        file_size: int,
        sha256: str,
        changelog: str | None,
        force_update: bool,
        min_supported_version_code: int | None,
    ) -> AppRelease:
        release = AppRelease(
            platform=platform,
            version_name=version_name,
            version_code=version_code,
            file_name=file_name,
            bucket_name=bucket_name,
            storage_key=storage_key,
            content_type=content_type,
            file_size=file_size,
            sha256=sha256,
            changelog=changelog,
            force_update=force_update,
            min_supported_version_code=min_supported_version_code,
            is_active=True,
        )
        session.add(release)
        await session.flush()
        return release

    async def deactivate_platform_releases(
        self,
        session: AsyncSession,
        *,
        platform: str,
    ) -> None:
        result = await session.execute(
            select(AppRelease).where(
                AppRelease.platform == platform,
                AppRelease.is_active.is_(True),
            )
        )
        for release in result.scalars().all():
            release.is_active = False
        await session.flush()
