from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.app_releases import (
    ApkUploadResponseData,
    AppVersionCheckResponseData,
    LatestAppReleaseResponseData,
)
from app.schemas.common import ApiResponse
from app.schemas.files import (
    CompleteUploadSessionRequest,
    CompleteUploadSessionResponseData,
    CreateUploadSessionRequest,
    CreateUploadSessionResponseData,
    GetAttachmentResponseData,
    InitAttachmentsRequest,
    InitAttachmentsResponseData,
    ListMessageAttachmentsResponseData,
)
from app.schemas.media_tags import (
    AssignAttachmentTagsRequest,
    AttachmentTagsResponseData,
)
from app.services.app_release_service import (
    check_android_apk_update,
    get_latest_android_apk_release,
    upload_android_apk_release,
)
from app.services.attachment_service import (
    get_attachment_metadata,
    list_message_attachments,
)
from app.services.file_service import (
    complete_upload_session,
    create_upload_session,
    init_attachments,
)
from app.services.media_tag_service import (
    assign_tags_to_attachments,
    remove_tag_from_attachment,
)

router = APIRouter()


def _extract_apk_upload_token(request: Request, form_token: str | None) -> str | None:
    if form_token:
        return form_token
    header_token = request.headers.get("X-APK-Upload-Token")
    if header_token:
        return header_token
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    return None


@router.post(
    "/upload-sessions",
    response_model=ApiResponse[CreateUploadSessionResponseData],
    summary="Create upload session",
    description="Create a file upload session for message attachments.",
)
async def create_upload_session_endpoint(
    payload: CreateUploadSessionRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[CreateUploadSessionResponseData]:
    """Start a new authenticated upload session for encrypted message attachments."""
    data = await create_upload_session(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=data)


@router.post(
    "/upload-sessions/{session_id}/attachments/init",
    response_model=ApiResponse[InitAttachmentsResponseData],
    summary="Init attachment uploads",
    description="Reserve attachment slots and return presigned upload URLs.",
)
async def init_attachments_endpoint(
    session_id: int,
    payload: InitAttachmentsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[InitAttachmentsResponseData]:
    """Create attachment records and presigned URLs within an upload session."""
    data = await init_attachments(
        session,
        current_user=current_user,
        session_id=session_id,
        payload=payload,
    )
    return ApiResponse(data=data)


@router.post(
    "/upload-sessions/{session_id}/complete",
    response_model=ApiResponse[CompleteUploadSessionResponseData],
    summary="Complete upload session",
    description="Validate uploaded objects in storage and mark the session completed.",
)
async def complete_upload_session_endpoint(
    session_id: int,
    payload: CompleteUploadSessionRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[CompleteUploadSessionResponseData]:
    """Finalize an authenticated file upload session after all objects are uploaded."""
    data = await complete_upload_session(
        session,
        current_user=current_user,
        session_id=session_id,
        payload=payload,
    )
    return ApiResponse(data=data)


@router.get(
    "/messages/{message_id}/attachments",
    response_model=ApiResponse[ListMessageAttachmentsResponseData],
    summary="List message attachments",
    description="Return attachment metadata for a message visible to the current user.",
)
async def list_message_attachments_endpoint(
    message_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListMessageAttachmentsResponseData]:
    """List metadata for attachments linked to a message."""
    data = await list_message_attachments(
        session,
        current_user=current_user,
        message_id=message_id,
    )
    return ApiResponse(data=data)


@router.get(
    "/attachments/{attachment_id}",
    response_model=ApiResponse[GetAttachmentResponseData],
    summary="Get attachment metadata",
    description="Return metadata and temporary download URL for a single attachment.",
)
async def get_attachment_metadata_endpoint(
    attachment_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[GetAttachmentResponseData]:
    """Return metadata for a single attachment available to the authenticated user."""
    data = await get_attachment_metadata(
        session,
        current_user=current_user,
        attachment_id=attachment_id,
    )
    return ApiResponse(data=data)


@router.post(
    "/attachments/{attachment_id}/media-tags",
    response_model=ApiResponse[AttachmentTagsResponseData],
    summary="Assign media tags to attachment",
)
async def assign_attachment_media_tags_endpoint(
    attachment_id: int,
    payload: AssignAttachmentTagsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AttachmentTagsResponseData]:
    data = await assign_tags_to_attachments(
        session,
        current_user=current_user,
        attachment_id=attachment_id,
        payload=payload,
    )
    return ApiResponse(data=data)


@router.delete(
    "/attachments/{attachment_id}/media-tags/{tag_id}",
    response_model=ApiResponse[AttachmentTagsResponseData],
    summary="Remove media tag from attachment",
)
async def remove_attachment_media_tag_endpoint(
    attachment_id: int,
    tag_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AttachmentTagsResponseData]:
    data = await remove_tag_from_attachment(
        session,
        current_user=current_user,
        attachment_id=attachment_id,
        tag_id=tag_id,
    )
    return ApiResponse(data=data)


@router.post(
    "/apk/upload",
    response_model=ApiResponse[ApkUploadResponseData],
    summary="Upload Android APK release",
    description=(
        "Upload and publish a new Android APK without JWT authentication, "
        "using a dedicated release token supplied via form field, header "
        "or query string."
    ),
)
async def upload_apk_endpoint(
    request: Request,
    version_name: str = Form(...),
    version_code: int = Form(...),
    changelog: str | None = Form(default=None),
    token: str | None = Form(default=None),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ApkUploadResponseData]:
    """Publish a new Android APK and notify eligible client devices."""
    data = await upload_android_apk_release(
        session,
        upload_token=_extract_apk_upload_token(request, token),
        version_name=version_name,
        version_code=version_code,
        changelog=changelog,
        file=file,
    )
    return ApiResponse(data=data)


@router.get(
    "/apk/latest",
    response_model=ApiResponse[LatestAppReleaseResponseData],
    summary="Get latest Android APK",
    description=(
        "Return metadata and a temporary download URL for the latest Android APK."
    ),
)
async def get_latest_apk_endpoint(
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[LatestAppReleaseResponseData]:
    """Fetch the latest published Android APK release."""
    data = await get_latest_android_apk_release(session)
    return ApiResponse(data=data)


@router.get(
    "/apk/check",
    response_model=ApiResponse[AppVersionCheckResponseData],
    summary="Check Android app version",
    description=(
        "Compare the client build number with the latest published Android APK "
        "and return whether an update is available."
    ),
)
async def check_apk_version_endpoint(
    version_code: int = Query(
        ...,
        ge=1,
        description="Current client Android version_code/build number.",
    ),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[AppVersionCheckResponseData]:
    """Compare the caller's version_code against the latest published APK release."""
    data = await check_android_apk_update(
        session,
        current_version_code=version_code,
    )
    return ApiResponse(data=data)
