from collections.abc import Awaitable, Callable

from connhex.auth import Auth, BearerAuth, SessionCookieAuth
from fastmcp.server.dependencies import get_access_token, get_http_headers

from connhex_mcp.auth.credentials import CredentialsProvider
from connhex_mcp.auth.session import (
    extract_bearer_from_headers,
    extract_session_cookie,
)
from connhex_mcp.config import MCPSettings


def _fastmcp_validated_token() -> str | None:
    """Return the fastmcp-validated OAuth access token, if any."""
    try:
        access_token = get_access_token()
    except Exception:
        return None
    if access_token and access_token.token:
        return access_token.token
    return None


def build_auth_provider(
    settings: MCPSettings,
) -> Callable[[], Awaitable[Auth]]:
    """Build a per-request authentication provider for this MCP server.

    Priority:
      1. In remote mode, prefer the fastmcp-validated managed session token.
      2. Bearer token from the incoming request's Authorization header.
      3. fastmcp-validated token (as fallback in local mode).
      4. Connhex session cookie from the incoming request.
      5. Static `session_cookie` from settings.
      6. Static `bearer_token` from settings.
      7. Username/password credentials (auto-refreshing).
    """
    creds = (
        CredentialsProvider(
            str(settings.instance_url), settings.username, settings.password
        )
        if settings.username and settings.password
        else None
    )
    prefer_validated = settings.public_url is not None

    async def resolve() -> Auth:
        if prefer_validated:
            tok = _fastmcp_validated_token()
            if tok:
                return BearerAuth(tok)

        headers = get_http_headers() or {}
        bearer = extract_bearer_from_headers(headers)
        if bearer:
            return BearerAuth(bearer.removeprefix("Bearer ").strip())

        tok = _fastmcp_validated_token()
        if tok:
            return BearerAuth(tok)

        session_cookie = extract_session_cookie(headers)
        if session_cookie:
            return SessionCookieAuth(session_cookie)

        if settings.session_cookie:
            return SessionCookieAuth(settings.session_cookie)

        if settings.bearer_token:
            return BearerAuth(settings.bearer_token)

        if creds is not None:
            return BearerAuth(await creds.get_token())

        raise RuntimeError(
            "No authentication available for this MCP request. "
            "Configure credentials, a token, or ensure session headers "
            "are forwarded."
        )

    return resolve
