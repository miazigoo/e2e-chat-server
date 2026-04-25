from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.app_releases import ApkUploadResponseData, LatestAppReleaseResponseData
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
from app.services.app_release_service import (
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
)
async def create_upload_session_endpoint(
    payload: CreateUploadSessionRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[CreateUploadSessionResponseData]:
    data = await create_upload_session(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=data)


@router.post(
    "/upload-sessions/{session_id}/attachments/init",
    response_model=ApiResponse[InitAttachmentsResponseData],
)
async def init_attachments_endpoint(
    session_id: int,
    payload: InitAttachmentsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[InitAttachmentsResponseData]:
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
)
async def complete_upload_session_endpoint(
    session_id: int,
    payload: CompleteUploadSessionRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[CompleteUploadSessionResponseData]:
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
)
async def list_message_attachments_endpoint(
    message_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListMessageAttachmentsResponseData]:
    data = await list_message_attachments(
        session,
        current_user=current_user,
        message_id=message_id,
    )
    return ApiResponse(data=data)


@router.get(
    "/attachments/{attachment_id}",
    response_model=ApiResponse[GetAttachmentResponseData],
)
async def get_attachment_metadata_endpoint(
    attachment_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[GetAttachmentResponseData]:
    data = await get_attachment_metadata(
        session,
        current_user=current_user,
        attachment_id=attachment_id,
    )
    return ApiResponse(data=data)


@router.post(
    "/apk/upload",
    response_model=ApiResponse[ApkUploadResponseData],
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
)
async def get_latest_apk_endpoint(
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[LatestAppReleaseResponseData]:
    data = await get_latest_android_apk_release(session)
    return ApiResponse(data=data)
