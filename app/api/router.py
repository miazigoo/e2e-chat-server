from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.files import router as files_router
from app.api.v1.keys import router as keys_router
from app.api.v1.messages import router as messages_router
from app.api.v1.sync import router as sync_router
from app.api.v1.users import router as users_router
from app.api.v1.ws import router as ws_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(keys_router, prefix="/keys", tags=["keys"])
api_router.include_router(
    conversations_router, prefix="/conversations", tags=["conversations"]
)
api_router.include_router(messages_router, prefix="/messages", tags=["messages"])
api_router.include_router(files_router, prefix="/files", tags=["files"])
api_router.include_router(sync_router, prefix="/sync", tags=["sync"])
api_router.include_router(ws_router, tags=["ws"])
