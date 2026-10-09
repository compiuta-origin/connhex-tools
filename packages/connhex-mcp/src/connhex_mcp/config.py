from connhex.urls import DEFAULT_INSTANCE_URL
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolTransformOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    title: str | None = None


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONNHEX_", extra="ignore")

    instance_url: HttpUrl = Field(
        default=DEFAULT_INSTANCE_URL,
        description="Connhex instance URL",
    )
    bearer_token: str | None = Field(
        default=None,
        description="Static bearer token (local mode fallback).",
    )
    session_cookie: str | None = Field(
        default=None,
        description="Static chx_auth_session cookie value (local mode fallback).",
    )
    username: str | None = Field(
        default=None,
        description="Username for password auth (local mode fallback).",
    )
    password: str | None = Field(
        default=None,
        description="Password for password auth (local mode fallback).",
    )
    public_url: str | None = Field(
        default=None,
        description="Public base URL, required for remote mode",
    )
    oauth_client_store_path: str | None = Field(
        default=None,
        description="SQLite path for OAuth clients and encrypted sessions.",
    )
    oauth_session_encryption_key: str | None = Field(
        default=None,
        repr=False,
        description="Stable Fernet key for encrypted remote OAuth sessions.",
    )
    kratos_admin_url: HttpUrl | None = Field(
        default=None,
        description="Internal Kratos admin URL for preventive session extension.",
    )
    openai_apps_challenge_token: str | None = Field(
        default=None,
        description="OpenAI Apps domain verification challenge token",
    )
    log_config_path: str | None = Field(
        default=None, description="Path to logging config JSON"
    )
    disabled_tools: list[str] | None = Field(
        default=None, description="Tool names to hide from the LLM"
    )
    tool_transforms: dict[str, ToolTransformOverride] | None = Field(
        default=None,
        description="JSON object mapping tool names to description/title overrides",
    )

    @field_validator("disabled_tools", mode="before")
    @classmethod
    def parse_comma_separated(cls, v: object) -> object:
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return v
