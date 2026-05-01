from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MediaTagSchema(BaseModel):
    tag_id: int
    conversation_id: int
    name: str
    color: str | None = None
    created_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class ListMediaTagsResponseData(BaseModel):
    items: list[MediaTagSchema] = Field(default_factory=list)


class CreateMediaTagRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=32)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class UpdateMediaTagRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, max_length=32)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class AssignAttachmentTagsRequest(BaseModel):
    tag_ids: list[int] = Field(min_length=1, max_length=20)

    @field_validator("tag_ids")
    @classmethod
    def validate_tag_ids_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("tag_ids must be unique")
        return value


class AttachmentTagsResponseData(BaseModel):
    attachment_id: int
    items: list[MediaTagSchema] = Field(default_factory=list)
