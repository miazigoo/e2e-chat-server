from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
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
