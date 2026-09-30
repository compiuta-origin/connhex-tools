from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from connhex.schemas._base import ConnhexBaseModel


class IdentityAddress(ConnhexBaseModel):
    value: str
    via: str
    id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VerifiableIdentityAddress(IdentityAddress):
    verified: bool = False
    status: str | None = None
    verified_at: datetime | None = None


class Identity(ConnhexBaseModel):
    id: str
    schema_id: str | None = None
    schema_url: str | None = None
    state: str | None = None
    state_changed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    organization_id: str | None = None
    traits: dict[str, Any] = Field(default_factory=dict)
    metadata_public: Any = None
    metadata_admin: Any = None
    recovery_addresses: list[IdentityAddress] = Field(default_factory=list)
    verifiable_addresses: list[VerifiableIdentityAddress] = Field(
        default_factory=list
    )

    @model_validator(mode="before")
    @classmethod
    def _omit_credentials(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k != "credentials"}
        return value


class IdentitiesPage(ConnhexBaseModel):
    identities: list[Identity]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None = None
