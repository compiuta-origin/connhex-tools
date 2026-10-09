import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from connhex.aio.auth import PASSWORD_LOGIN_TIMEOUT, password_login
from connhex.urls import build_accounts_url
from fastmcp.server.auth.auth import AccessToken, OAuthProvider
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import build_metadata, cors_middleware
from mcp.server.auth.settings import (
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from pydantic import ValidationError
from starlette.authentication import AuthenticationError
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from starlette.routing import Route

from connhex_mcp.auth.store import (
    OAuthConnection,
    OAuthConnectionStore,
    SQLiteOAuthConnectionStore,
)
from connhex_mcp.auth.templates import render_error_page, render_login_page
from connhex_mcp.config import MCPSettings

logger = logging.getLogger(__name__)

FLOW_TTL = 300
CODE_TTL = 300
SESSION_CHECK_INTERVAL = 60
SESSION_EXTENSION_WINDOW = 6 * 60 * 60
TOKEN_CACHE_TTL = 60


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class PendingAuthorization:
    client: OAuthClientInformationFull
    params: AuthorizationParams
    expires_at: float


@dataclass(frozen=True)
class KratosSession:
    session_id: str
    identity_id: str
    expires_at: float


class ConnhexOAuthProvider(OAuthProvider):
    """OAuth provider that authenticates users via Connhex.

    Implements the full OAuth 2.0 authorization code flow with PKCE.
    """

    def __init__(self, settings: MCPSettings):
        assert settings.public_url, (
            "CONNHEX_PUBLIC_URL is required for remote mode"
        )

        super().__init__(
            base_url=settings.public_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
            ),
            revocation_options=RevocationOptions(enabled=True),
        )

        self.settings = settings
        self.accounts_url = build_accounts_url(str(settings.instance_url))
        if not settings.oauth_client_store_path:
            raise ValueError("CONNHEX_OAUTH_CLIENT_STORE_PATH is required")
        if not settings.oauth_session_encryption_key:
            raise ValueError("CONNHEX_OAUTH_SESSION_ENCRYPTION_KEY is required")
        if not settings.kratos_admin_url:
            raise ValueError("CONNHEX_KRATOS_ADMIN_URL is required")
        self._store: OAuthConnectionStore = SQLiteOAuthConnectionStore(
            settings.oauth_client_store_path,
            settings.oauth_session_encryption_key,
        )
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._code_tokens: dict[str, str] = {}
        self._pending_flows: dict[str, PendingAuthorization] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._maintenance_task: asyncio.Task | None = None

    async def get_client(
        self, client_id: str
    ) -> OAuthClientInformationFull | None:
        return self._store.get_client(client_id)

    async def register_client(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        self._store.put_client(client_info)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Store the pending flow and redirect to the login form."""
        flow_id = secrets.token_urlsafe(32)
        self._pending_flows[flow_id] = PendingAuthorization(
            client=client,
            params=params,
            expires_at=_now() + FLOW_TTL,
        )

        base = str(self.base_url).rstrip("/")
        return f"{base}/oauth/login?flow_id={flow_id}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        code_obj = self._auth_codes.get(authorization_code)
        if code_obj is None:
            return None
        if code_obj.client_id != client.client_id:
            return None
        if code_obj.expires_at and code_obj.expires_at < _now():
            self._auth_codes.pop(authorization_code, None)
            self._code_tokens.pop(authorization_code, None)
            return None
        return code_obj

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """Exchange an authorization code for the ory_st_* session token."""
        code_str = authorization_code.code
        ory_token = self._code_tokens.pop(code_str, None)
        self._auth_codes.pop(code_str, None)

        if not ory_token:
            raise TokenError(
                error="invalid_grant",
                error_description="Authorization code not found or expired",
            )

        session = await self._get_session(ory_token)
        if session is None:
            raise TokenError(
                error="invalid_grant",
                error_description="Session token is no longer valid",
            )
        self._store.put_connection(
            OAuthConnection(
                token=ory_token,
                session_id=session.session_id,
                identity_id=session.identity_id,
                client_id=client.client_id or "",
                expires_at=session.expires_at,
                scopes=authorization_code.scopes,
            )
        )
        logger.info("Token exchange complete for client %s", client.client_id)
        return OAuthToken(access_token=ory_token, token_type="Bearer")

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Load local ownership for revocation, even during a Kratos outage."""
        record = self._get_active_connection(token)
        if record is None:
            return None
        return AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=record.scopes,
            expires_at=int(record.expires_at),
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """Only accept managed sessions; cache Kratos validation for <=60s."""
        record = self._get_active_connection(token)
        if record is None:
            return None
        now = _now()
        cached = self._access_tokens.get(token)
        if cached and (cached.expires_at or 0) > now:
            return cached
        try:
            session = await self._validate_connection(record)
        except Exception:
            logger.warning(
                "Session validation unavailable for %s", record.session_id
            )
            raise AuthenticationError(
                "Session validation unavailable"
            ) from None
        if session is None:
            return None
        access_token = AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=record.scopes,
            expires_at=int(min(now + TOKEN_CACHE_TTL, session.expires_at)),
        )
        self._access_tokens[token] = access_token
        return access_token

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ):
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token,
        scopes: list[str],
    ) -> OAuthToken:
        raise TokenError(
            error="unsupported_grant_type",
            error_description="Refresh tokens are not supported",
        )

    async def revoke_token(self, token) -> None:
        token_str = token.token if hasattr(token, "token") else str(token)
        self._invalidate(token_str, "revoked")

    async def start(self) -> None:
        """Start maintenance at server startup, independently of OAuth traffic."""
        if self._maintenance_task is None or self._maintenance_task.done():
            self._maintenance_task = asyncio.create_task(
                self._maintenance_loop()
            )
            logger.info("OAuth session maintenance started (interval=60s)")

    async def close(self) -> None:
        if self._maintenance_task is not None:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
            self._maintenance_task = None
            logger.info("OAuth session maintenance stopped")

    async def _maintenance_loop(self) -> None:
        while True:
            try:
                self._cleanup_once()
                await self._maintain_sessions()
            except Exception:
                # Never log HTTP exception details: they can contain headers.
                logger.error("OAuth maintenance failed; retrying in 60 seconds")
            await asyncio.sleep(SESSION_CHECK_INTERVAL)

    def _cleanup_once(self) -> None:
        now = _now()
        for flow_id, flow in list(self._pending_flows.items()):
            if flow.expires_at < now:
                self._pending_flows.pop(flow_id, None)
        for code, record in list(self._auth_codes.items()):
            if (record.expires_at or 0) < now:
                self._auth_codes.pop(code, None)
                self._code_tokens.pop(code, None)
        for token, record in list(self._access_tokens.items()):
            if (record.expires_at or 0) <= now:
                self._access_tokens.pop(token, None)

    def _invalidate(self, token: str, state: str = "invalid") -> None:
        self._store.deactivate(token, state)
        self._access_tokens.pop(token, None)

    async def _maintain_sessions(self) -> None:
        semaphore = asyncio.Semaphore(8)

        async def maintain(record: OAuthConnection) -> None:
            async with semaphore:
                try:
                    await self._maintain_session(record)
                except Exception:
                    logger.warning(
                        "Session check/extension failed for %s; retrying",
                        record.session_id,
                    )

        await asyncio.gather(
            *(maintain(record) for record in self._store.active_connections())
        )

    async def _maintain_session(self, record: OAuthConnection) -> None:
        if self._get_active_connection(record.token) is None:
            return
        session = await self._validate_connection(record)
        if session is None:
            return
        remaining = session.expires_at - _now()
        if remaining > SESSION_EXTENSION_WINDOW:
            return
        # Never knowingly extend expired sessions: Kratos v1.1 would persist
        # active=false while updating their expiry.
        if remaining <= 0:
            self._invalidate(record.token)
            return
        if not await self._extend_session(record.session_id):
            self._invalidate(record.token)
            return
        # Confirm using whoami, including when PATCH returns an empty body.
        confirmed = await self._validate_connection(record)
        if confirmed is None:
            return
        self._access_tokens.pop(record.token, None)
        if confirmed.expires_at > session.expires_at:
            logger.info(
                "Session %s extended until %s",
                record.session_id,
                datetime.fromtimestamp(confirmed.expires_at, UTC).isoformat(),
            )
        else:
            logger.debug("Session %s not yet extendable", record.session_id)

    def _get_active_connection(self, token: str) -> OAuthConnection | None:
        record = self._store.get_connection(token)
        return (
            record if record is not None and record.state == "active" else None
        )

    async def _validate_connection(
        self, record: OAuthConnection
    ) -> KratosSession | None:
        """Validate identity/session binding without undoing a concurrent revoke."""
        session = await self._get_session(record.token)
        if (
            session is None
            or session.session_id != record.session_id
            or session.identity_id != record.identity_id
        ):
            self._invalidate(record.token)
            logger.info("Session %s is no longer valid", record.session_id)
            return None
        if self._get_active_connection(record.token) is None:
            return None
        if session.expires_at != record.expires_at:
            self._store.update_expiry(record.token, session.expires_at)
        return session

    async def _extend_session(self, session_id: str) -> bool:
        """PATCH the internal admin endpoint; report definitive disappearance."""
        url = (
            str(self.settings.kratos_admin_url).rstrip("/")
            + f"/admin/sessions/{session_id}/extend"
        )
        async with httpx.AsyncClient(timeout=PASSWORD_LOGIN_TIMEOUT) as client:
            response = await client.patch(url)
        if response.status_code in (404, 410):
            return False
        response.raise_for_status()
        return True

    def get_middleware(self) -> list:
        middleware = super().get_middleware()
        for item in middleware:
            if item.cls is AuthenticationMiddleware:
                item.kwargs["on_error"] = lambda connection, error: (
                    JSONResponse(
                        {"error": "temporarily_unavailable"},
                        status_code=503,
                        headers={"Retry-After": str(SESSION_CHECK_INTERVAL)},
                    )
                )
        return middleware

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """Combine OAuth endpoints, the login form, and static resources."""
        routes = self._oauth_routes(mcp_path)
        routes.extend(
            [
                Route("/oauth/login", self._handle_login_page, methods=["GET"]),
                Route(
                    "/oauth/login", self._handle_login_submit, methods=["POST"]
                ),
                Route("/favicon.ico", self._handle_favicon, methods=["GET"]),
                Route("/connhex-logo.webp", self._handle_logo, methods=["GET"]),
            ]
        )
        if self.settings.openai_apps_challenge_token:
            routes.append(
                Route(
                    "/.well-known/openai-apps-challenge",
                    self._handle_openai_apps_challenge,
                    methods=["GET"],
                )
            )
        return routes

    def _oauth_routes(self, mcp_path: str | None) -> list[Route]:
        """Override SDK endpoints that assume refresh-token support."""
        routes = super().get_routes(mcp_path)
        metadata = build_metadata(
            self.base_url,
            self.service_documentation_url,
            self.client_registration_options,
            self.revocation_options,
        )
        metadata.grant_types_supported = ["authorization_code"]
        overrides = {
            "/.well-known/oauth-authorization-server": Route(
                "/.well-known/oauth-authorization-server",
                cors_middleware(
                    MetadataHandler(metadata).handle, ["GET", "OPTIONS"]
                ),
                methods=["GET", "OPTIONS"],
            ),
            # SDK registration requires both authorization_code and
            # refresh_token. Our handler retains SDK metadata validation
            # while registering only the grant we actually implement.
            "/register": Route(
                "/register",
                cors_middleware(self._handle_registration, ["POST", "OPTIONS"]),
                methods=["POST", "OPTIONS"],
            ),
        }
        return [overrides.get(route.path, route) for route in routes]

    async def _handle_registration(self, request: Request) -> Response:
        def invalid() -> Response:
            return JSONResponse(
                {
                    "error": "invalid_client_metadata",
                    "error_description": "Invalid authorization-code client metadata",
                },
                status_code=400,
            )

        try:
            metadata = OAuthClientMetadata.model_validate(await request.json())
        except (ValidationError, ValueError):
            return invalid()
        if (
            "authorization_code" not in metadata.grant_types
            or set(metadata.grant_types)
            - {"authorization_code", "refresh_token"}
            or metadata.response_types != ["code"]
        ):
            return invalid()
        options = self.client_registration_options
        if metadata.scope is None and options.default_scopes is not None:
            metadata.scope = " ".join(options.default_scopes)
        if options.valid_scopes is not None and not set(
            (metadata.scope or "").split()
        ).issubset(options.valid_scopes):
            return invalid()
        auth_method = (
            metadata.token_endpoint_auth_method or "client_secret_post"
        )
        issued_at = int(_now())
        client = OAuthClientInformationFull(
            **metadata.model_dump(
                exclude={"grant_types", "token_endpoint_auth_method"}
            ),
            grant_types=["authorization_code"],
            token_endpoint_auth_method=auth_method,
            client_id=secrets.token_urlsafe(32),
            client_secret=(
                secrets.token_hex(32) if auth_method != "none" else None
            ),
            client_id_issued_at=issued_at,
            client_secret_expires_at=(
                issued_at + options.client_secret_expiry_seconds
                if options.client_secret_expiry_seconds is not None
                else None
            ),
        )
        await self.register_client(client)
        return JSONResponse(
            client.model_dump(mode="json", exclude_none=True),
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )

    async def _handle_openai_apps_challenge(
        self, request: Request
    ) -> PlainTextResponse:
        return PlainTextResponse(
            self.settings.openai_apps_challenge_token or ""
        )

    async def _handle_favicon(self, request: Request) -> Response:
        data = (
            Path(__file__).parent.parent / "res" / "favicon.ico"
        ).read_bytes()
        return Response(content=data, media_type="image/x-icon")

    async def _handle_logo(self, request: Request) -> Response:
        data = (
            Path(__file__).parent.parent / "res" / "connhex-logo.webp"
        ).read_bytes()
        return Response(content=data, media_type="image/webp")

    async def _handle_login_page(self, request: Request) -> Response:
        """Serve the HTML login form."""
        flow_id = request.query_params.get("flow_id", "")

        if flow_id not in self._pending_flows:
            return HTMLResponse(
                content=render_error_page(
                    "Invalid or expired login link. "
                    "Please restart the connection from your MCP client."
                ),
                status_code=400,
            )

        return HTMLResponse(content=render_login_page(flow_id), status_code=200)

    async def _handle_login_submit(self, request: Request) -> Response:
        """Process login credentials via Kratos and redirect with code."""
        form = await request.form()
        flow_id = str(form.get("flow_id", ""))
        identifier = str(form.get("identifier", ""))
        password = str(form.get("password", ""))

        flow = self._pending_flows.get(flow_id)
        if not flow or flow.expires_at < _now():
            self._pending_flows.pop(flow_id, None)
            return HTMLResponse(
                content=render_error_page(
                    "Login session expired. "
                    "Please restart from your MCP client."
                ),
                status_code=400,
            )

        if not identifier or not password:
            return HTMLResponse(
                content=render_login_page(
                    flow_id,
                    error="Email and password are required.",
                ),
                status_code=400,
            )

        try:
            ory_token = await password_login(
                str(self.settings.instance_url), identifier, password
            )
            del password
            logger.info("Successful login for %s", identifier)
        except ValueError:
            logger.warning("Login failed for %s", identifier)
            return HTMLResponse(
                content=render_login_page(
                    flow_id,
                    error="Invalid email or password.",
                ),
                status_code=401,
            )
        except Exception:
            logger.warning("Login service error for %s", identifier)
            return HTMLResponse(
                content=render_login_page(
                    flow_id,
                    error="Login service unavailable. Please try again.",
                ),
                status_code=502,
            )

        # Generate authorization code
        params: AuthorizationParams = flow.params
        client: OAuthClientInformationFull = flow.client

        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=_now() + CODE_TTL,
            client_id=client.client_id or "",
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=(
                params.redirect_uri_provided_explicitly
            ),
        )
        self._code_tokens[code] = ory_token

        # Clean up the pending flow
        self._pending_flows.pop(flow_id, None)

        location = construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )

        return Response(
            status_code=302,
            headers={"Location": location},
        )

    async def _get_session(self, token: str) -> KratosSession | None:
        """Validate against Kratos; distinguish invalid auth from outages."""
        async with httpx.AsyncClient(timeout=PASSWORD_LOGIN_TIMEOUT) as client:
            response = await client.get(
                f"{self.accounts_url}/auth/sessions/whoami",
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code in (401, 403):
            return None
        response.raise_for_status()
        session = response.json()
        # Reject malformed payloads without deactivating persisted state.
        session_id = str(UUID(session["id"]))
        identity_id = str(UUID(session["identity"]["id"]))
        expiry = datetime.fromisoformat(session["expires_at"])
        if expiry.tzinfo is None:
            raise ValueError("Session expiry must include a timezone")
        expires_at = expiry.timestamp()
        if not isinstance(session["active"], bool):
            raise ValueError("Invalid session state")
        if (
            not session["active"]
            or session["identity"]["state"] != "active"
            or expires_at <= _now()
        ):
            return None
        return KratosSession(session_id, identity_id, expires_at)
