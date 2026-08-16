from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(
        min_length=1,
        max_length=100,
    )

    dm_message: str = Field(
        min_length=1,
        max_length=5000,
    )

    @field_validator("keyword", "dm_message")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("value cannot be empty")

        return value


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    keyword: str
    dm_message: str


class WebhookUser(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    user_id: str = Field(
        min_length=1,
        max_length=255,
    )

    username: str | None = Field(
        default=None,
        max_length=255,
    )


class WebhookData(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    comment_id: str = Field(
        min_length=1,
        max_length=255,
    )

    post_id: str | None = Field(
        default=None,
        max_length=255,
    )

    text: str | None = Field(
        default=None,
        max_length=10000,
    )

    created_at: str | None = None

    from_: WebhookUser = Field(
        alias="from",
    )


class WebhookEvent(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
    )

    event_id: str = Field(
        min_length=1,
        max_length=255,
    )

    event_type: str = Field(
        min_length=1,
        max_length=100,
    )

    sent_at: datetime

    data: WebhookData