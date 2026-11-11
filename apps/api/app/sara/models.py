from uuid import UUID

from pydantic import Field, field_validator

from ..crm.models import Input


class ConversationCreate(Input):
    title: str = Field(default="Nueva conversación", min_length=1, max_length=120)


class ConversationEdit(Input):
    title: str = Field(min_length=1, max_length=120)


class MessageInput(Input):
    request_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=4)

    @field_validator("attachment_ids")
    @classmethod
    def unique_files(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate_attachment")
        return value


class AttachmentInput(Input):
    filename: str = Field(min_length=1, max_length=120)
    mime_type: str = Field(min_length=1, max_length=80)
    data_base64: str = Field(min_length=4, max_length=699052)
