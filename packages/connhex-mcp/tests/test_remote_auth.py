import base64
import hashlib
import logging
import sqlite3
from datetime import UTC, datetime
from threading import Event

import httpx
import pytest
from connhex.urls import DEFAULT_INSTANCE_URL
from connhex_mcp.auth import remote
from connhex_mcp.auth.remote import (
    ConnhexOAuthProvider,
)
from connhex_mcp.auth.store import OAuthConnection
from connhex_mcp.config import MCPSettings
from connhex_mcp.mcp_instance import mcp
from cryptography.fernet import Fernet
from fastmcp import FastMCP
from mcp.shared.auth import OAuthClientInformationFull
from starlette.applications import Starlette
from starlette.testclient import TestClient


def make_settings(
    openai_apps_challenge_token: str | None = None,
    oauth_client_store_path: str | None = None,
) -> MCPSettings:
    return MCPSettings(
        instance_url="https://connhex.com",
        public_url="https://mcp.connhex.com",
        openai_apps_challenge_token=openai_apps_challenge_token,
        **(
            {"oauth_client_store_path": oauth_client_store_path}
            if oauth_client_store_path is not None
            else {}
        ),
    )


def test_settings_default_to_saas_instance_url(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("CONNHEX_INSTANCE_URL", raising=False)

    settings = MCPSettings()

    assert str(settings.instance_url).rstrip("/") == DEFAULT_INSTANCE_URL


def test_openai_apps_challenge_route_is_absent_without_token():
    provider = ConnhexOAuthProvider(make_settings())
    routes = provider.get_routes("/")

    assert all(
        route.path != "/.well-known/openai-apps-challenge" for route in routes
    )


def test_openai_apps_challenge_route_returns_configured_token():
    provider = ConnhexOAuthProvider(make_settings("challenge-token"))
    app = Starlette(routes=provider.get_routes("/"))
    client = TestClient(app, raise_server_exceptions=True)

    response = client.get("/.well-known/openai-apps-challenge")

    assert response.status_code == 200
    assert response.text == "challenge-token"
    assert response.headers["content-type"].startswith("text/plain")


def make_oauth_client(
    client_id: str = "client-1",
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret="client-secret",
        client_id_issued_at=1_717_171_717,
        client_secret_expires_at=None,
        redirect_uris=["https://chatgpt.com/connector/oauth/test"],
        token_endpoint_auth_method="client_secret_post",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="",
        client_name="ChatGPT",
    )


@pytest.fixture(autouse=True)
def remote_settings(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CONNHEX_OAUTH_CLIENT_STORE_PATH", str(tmp_path / "oauth.sqlite")
    )
    monkeypatch.setenv(
        "CONNHEX_OAUTH_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    monkeypatch.setenv(
        "CONNHEX_ACCOUNTS_ADMIN_URL",
        "http://account-admin.auth.svc.cluster.local",
    )


@pytest.mark.parametrize(
    "field,env",
    [
        ("oauth_client_store_path", "CONNHEX_OAUTH_CLIENT_STORE_PATH"),
        (
            "oauth_session_encryption_key",
            "CONNHEX_OAUTH_SESSION_ENCRYPTION_KEY",
        ),
        ("accounts_admin_url", "CONNHEX_ACCOUNTS_ADMIN_URL"),
    ],
)
def test_remote_requires_persistent_configuration(field, env):
    settings = make_settings().model_copy(update={field: None})
    with pytest.raises(ValueError, match=env):
        ConnhexOAuthProvider(settings)


def test_old_admin_environment_name_is_not_supported(monkeypatch):
    monkeypatch.delenv("CONNHEX_ACCOUNTS_ADMIN_URL")
    monkeypatch.setenv(
        "CONNHEX_KRATOS_ADMIN_URL",
        "http://account-admin.auth.svc.cluster.local",
    )
    settings = make_settings()
    assert settings.accounts_admin_url is None
    with pytest.raises(ValueError, match="CONNHEX_ACCOUNTS_ADMIN_URL"):
        ConnhexOAuthProvider(settings)


@pytest.mark.asyncio
async def test_sqlite_store_persists_registered_clients_after_restart(
    tmp_path,
):
    db_path = tmp_path / "oauth-clients.sqlite"
    first_provider = ConnhexOAuthProvider(
        make_settings(oauth_client_store_path=str(db_path))
    )
    client_info = make_oauth_client()

    await first_provider.register_client(client_info)

    restarted_provider = ConnhexOAuthProvider(
        make_settings(oauth_client_store_path=str(db_path))
    )

    persisted = await restarted_provider.get_client("client-1")
    assert persisted == client_info
    assert persisted is not None
    assert persisted.client_secret == "client-secret"
    assert persisted.token_endpoint_auth_method == "client_secret_post"
    assert persisted.redirect_uris == client_info.redirect_uris
    assert persisted.grant_types == ["authorization_code", "refresh_token"]
    assert persisted.response_types == ["code"]
    assert persisted.client_id_issued_at == 1_717_171_717


@pytest.mark.asyncio
async def test_authorize_accepts_persisted_client_after_restart(tmp_path):
    db_path = tmp_path / "oauth-clients.sqlite"
    first_provider = ConnhexOAuthProvider(
        make_settings(oauth_client_store_path=str(db_path))
    )
    await first_provider.register_client(make_oauth_client())

    restarted_provider = ConnhexOAuthProvider(
        make_settings(oauth_client_store_path=str(db_path))
    )
    app = Starlette(routes=restarted_provider.get_routes("/"))
    client = TestClient(app, raise_server_exceptions=True)

    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "client-1",
            "redirect_uri": "https://chatgpt.com/connector/oauth/test",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "state": "state-1",
            "resource": "https://mcp.connhex.com/",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "https://mcp.connhex.com/oauth/login?flow_id="
    )


def test_authorize_rejects_unknown_client(tmp_path):
    provider = ConnhexOAuthProvider(
        make_settings(
            oauth_client_store_path=str(tmp_path / "oauth-clients.sqlite")
        )
    )
    app = Starlette(routes=provider.get_routes("/"))
    client = TestClient(app, raise_server_exceptions=True)

    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "unknown-client",
            "redirect_uri": "https://chatgpt.com/connector/oauth/test",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "state": "state-1",
            "resource": "https://mcp.connhex.com/",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_request",
        "error_description": "Client ID 'unknown-client' not found",
        "state": "state-1",
    }


@pytest.mark.asyncio
async def test_sqlite_store_ignores_corrupt_client_rows(
    tmp_path, caplog: pytest.LogCaptureFixture
):
    db_path = tmp_path / "oauth-clients.sqlite"
    ConnhexOAuthProvider(make_settings(oauth_client_store_path=str(db_path)))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO oauth_clients (
                client_id,
                client_info,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            ("bad-client", "{not-json", 1, 1),
        )

    provider = ConnhexOAuthProvider(
        make_settings(oauth_client_store_path=str(db_path))
    )

    with caplog.at_level(logging.WARNING, logger=remote.logger.name):
        client_info = await provider.get_client("bad-client")

    assert client_info is None
    assert "Ignoring invalid persisted OAuth client bad-client" in caplog.text


def test_sqlite_store_requires_existing_parent_directory(tmp_path):
    missing_path = tmp_path / "missing" / "oauth-clients.sqlite"

    with pytest.raises(ValueError, match="does not exist"):
        ConnhexOAuthProvider(
            make_settings(oauth_client_store_path=str(missing_path))
        )


def test_sqlite_store_rejects_unusable_database_path(tmp_path):
    with pytest.raises(ValueError, match="Unable to initialize"):
        ConnhexOAuthProvider(
            make_settings(oauth_client_store_path=str(tmp_path))
        )


SID = "7210257e-6dc0-4bbb-ba3d-8647be2c7ce9"
IID = "7f86c740-c2d6-4e4f-83c1-a13838d2ab26"
TOKEN = "ory_st_test_only"


def session(expiry, active=True):
    return {
        "id": SID,
        "active": active,
        "expires_at": datetime.fromtimestamp(expiry, UTC).isoformat(),
        "identity": {"id": IID, "state": "active"},
    }


def add_connection(provider, expiry=2000):
    provider._store.put_connection(
        OAuthConnection(
            TOKEN,
            SID,
            IID,
            "client-1",
            expiry,
        )
    )


@pytest.fixture
def mock_http(monkeypatch):
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            remote.httpx,
            "AsyncClient",
            lambda **kwargs: original(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )

    return install


@pytest.mark.asyncio
async def test_exchange_wire_response_omits_expiry_and_refresh(mock_http):
    provider = ConnhexOAuthProvider(make_settings())
    await provider.register_client(make_oauth_client())
    verifier = "test-verifier"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    mock_http(
        lambda request: httpx.Response(200, json=session(remote._now() + 86400))
    )
    from mcp.server.auth.provider import AuthorizationCode

    code = AuthorizationCode(
        code="code",
        client_id="client-1",
        scopes=[],
        expires_at=remote._now() + 300,
        code_challenge=challenge,
        redirect_uri="https://chatgpt.com/connector/oauth/test",
        redirect_uri_provided_explicitly=True,
    )
    provider._auth_codes["code"] = code
    provider._code_tokens["code"] = TOKEN
    with TestClient(Starlette(routes=provider.get_routes("/"))) as client:
        response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "client-1",
                "client_secret": "client-secret",
                "code": "code",
                "code_verifier": verifier,
                "redirect_uri": "https://chatgpt.com/connector/oauth/test",
            },
        )
    assert response.status_code == 200
    assert response.json() == {"access_token": TOKEN, "token_type": "Bearer"}
    assert provider._store.get_connection(TOKEN).session_id == SID
    assert not provider._code_tokens


def test_metadata_and_dynamic_registration():
    provider = ConnhexOAuthProvider(make_settings())
    with TestClient(Starlette(routes=provider.get_routes("/"))) as client:
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert metadata["grant_types_supported"] == ["authorization_code"]
        assert metadata["revocation_endpoint"].endswith("/revoke")
        response = client.post(
            "/register",
            json={
                "redirect_uris": ["https://chatgpt.com/connector/oauth/test"],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
    assert response.status_code == 201
    assert response.json()["client_id"]


@pytest.mark.asyncio
async def test_connection_survives_restart_encrypted(mock_http):
    settings = make_settings()
    provider = ConnhexOAuthProvider(settings)
    add_connection(provider, remote._now() + 86400)
    mock_http(
        lambda request: httpx.Response(200, json=session(remote._now() + 86400))
    )
    restarted = ConnhexOAuthProvider(settings)
    token = await restarted.verify_token(TOKEN)
    assert token.token == TOKEN
    assert token.client_id == "client-1"
    assert token.expires_at <= remote._now() + 60
    with sqlite3.connect(settings.oauth_client_store_path) as conn:
        payload = str(
            conn.execute("SELECT * FROM oauth_connections").fetchall()
        )
    assert TOKEN not in payload
    assert "password" not in payload
    assert TOKEN not in repr(restarted._store.get_connection(TOKEN))
    wrong_key = settings.model_copy(
        update={"oauth_session_encryption_key": Fernet.generate_key().decode()}
    )
    with pytest.raises(ValueError, match="Unable to decrypt"):
        ConnhexOAuthProvider(wrong_key)


@pytest.mark.asyncio
async def test_unknown_token_never_reaches_accounts(mock_http):
    provider = ConnhexOAuthProvider(make_settings())

    def unexpected(request):
        raise AssertionError("Unknown tokens must be rejected locally")

    mock_http(unexpected)
    assert await provider.verify_token("old-unmanaged-token") is None


@pytest.mark.asyncio
async def test_validation_cache_is_bounded_and_detects_revocation(
    monkeypatch, mock_http
):
    now = 1000
    monkeypatch.setattr(remote, "_now", lambda: now)
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider)
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(200, json=session(2000))
            if len(calls) == 1
            else httpx.Response(401)
        )

    mock_http(handler)
    assert await provider.verify_token(TOKEN)
    now = 1059
    assert await provider.verify_token(TOKEN)
    assert len(calls) == 1
    now = 1060
    assert await provider.verify_token(TOKEN) is None
    assert provider._store.get_connection(TOKEN).state == "invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch_status,advanced", [(200, True), (204, True), (200, False)]
)
async def test_preventive_extension_without_traffic(
    monkeypatch, mock_http, patch_status, advanced
):
    monkeypatch.setattr(remote, "_now", lambda: 1000)
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider)
    calls = []
    expiry = 2000

    def handler(request):
        nonlocal expiry
        calls.append((request.method, str(request.url)))
        if request.method == "PATCH":
            assert (
                str(request.url)
                == f"http://account-admin.auth.svc.cluster.local/admin/sessions/{SID}/extend"
            )
            assert "authorization" not in request.headers
            if advanced:
                expiry = 87400
            return httpx.Response(patch_status)
        return httpx.Response(200, json=session(expiry))

    mock_http(handler)
    await provider._maintain_sessions()
    assert [method for method, _ in calls] == ["GET", "PATCH", "GET"]
    assert provider._store.get_connection(TOKEN).expires_at == expiry
    assert provider._store.get_connection(TOKEN).state == "active"
    assert not hasattr(provider, "_renewal_records")
    calls.clear()
    await provider._maintain_sessions()
    assert len(calls) == (1 if advanced else 3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (401, None),
        (200, session(999)),
        (200, session(2000, False)),
        (200, {**session(2000), "identity": {"id": IID, "state": "inactive"}}),
        (200, {**session(2000), "id": "11111111-1111-1111-1111-111111111111"}),
    ],
)
async def test_invalid_sessions_never_extended(
    monkeypatch, mock_http, status, body
):
    monkeypatch.setattr(remote, "_now", lambda: 1000)
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(status, json=body)

    mock_http(handler)
    await provider._maintain_sessions()
    assert provider._store.get_connection(TOKEN).state == "invalid"
    await provider._maintain_sessions()
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["whoami", "patch", "confirmation"])
async def test_temporary_failures_retry_without_losing_state(
    monkeypatch, mock_http, stage
):
    monkeypatch.setattr(remote, "_now", lambda: 1000)
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider)
    calls = []

    def handler(request):
        calls.append(request)
        fail = (
            stage == "whoami"
            and len(calls) == 1
            or stage == "patch"
            and request.method == "PATCH"
            or stage == "confirmation"
            and len(calls) == 3
        )
        return (
            httpx.Response(503)
            if fail
            else httpx.Response(200, json=session(2000))
        )

    mock_http(handler)
    await provider._maintain_sessions()
    assert provider._store.get_connection(TOKEN).state == "active"
    mock_http(lambda request: httpx.Response(200, json=session(2000)))
    await provider._maintain_sessions()
    assert provider._store.get_connection(TOKEN).state == "active"


def test_lifespan_checks_immediately_and_closes_task(monkeypatch, mock_http):
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider, remote._now() + 86400)
    checked = Event()

    def handler(request):
        checked.set()
        return httpx.Response(200, json=session(remote._now() + 86400))

    mock_http(handler)
    monkeypatch.setattr(mcp, "auth", provider)
    with TestClient(mcp.http_app(transport="streamable-http", path="/")):
        assert checked.wait(timeout=2)
        task = provider._maintenance_task
        assert not task.done()
    assert task.done()
    assert provider._maintenance_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("accounts_available", [True, False])
async def test_oauth_revoke_persists_and_stops_extension(
    mock_http, accounts_available
):
    settings = make_settings()
    provider = ConnhexOAuthProvider(settings)
    await provider.register_client(make_oauth_client())
    add_connection(provider, remote._now() + 86400)

    def handler(request):
        if not accounts_available:
            raise AssertionError("Revocation must not depend on Accounts")
        return httpx.Response(200, json=session(remote._now() + 86400))

    mock_http(handler)
    with TestClient(Starlette(routes=provider.get_routes("/"))) as client:
        response = client.post(
            "/revoke",
            data={
                "token": TOKEN,
                "client_id": "client-1",
                "client_secret": "client-secret",
                "token_type_hint": "access_token",
            },
        )
    assert response.status_code == 200
    restarted = ConnhexOAuthProvider(settings)
    assert await restarted.verify_token(TOKEN) is None
    assert not restarted._store.active_connections()


@pytest.mark.asyncio
async def test_cleanup_never_discards_idle_connections():
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider, remote._now() + 86400)
    provider._cleanup_once()
    assert len(provider._store.active_connections()) == 1


@pytest.mark.parametrize(
    "grants,expected",
    [
        (["authorization_code", "refresh_token"], 201),
        (["refresh_token"], 400),
        (["client_credentials"], 400),
    ],
)
def test_registration_only_grants_authorization_code(grants, expected):
    provider = ConnhexOAuthProvider(make_settings())
    with TestClient(Starlette(routes=provider.get_routes("/"))) as client:
        response = client.post(
            "/register",
            json={
                "redirect_uris": ["https://chatgpt.com/connector/oauth/test"],
                "grant_types": grants,
                "response_types": ["code"],
            },
        )
    assert response.status_code == expected
    if expected == 201:
        assert response.json()["grant_types"] == ["authorization_code"]


@pytest.mark.asyncio
async def test_validation_outage_and_malformed_payload_are_not_revocations(
    mock_http,
):
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider, remote._now() + 86400)
    for status, body in [(503, None), (200, {"unexpected": "payload"})]:
        mock_http(lambda request: httpx.Response(status, json=body))
        with pytest.raises(remote.AuthenticationError):
            await provider.verify_token(TOKEN)
        assert provider._store.get_connection(TOKEN).state == "active"
    mock_http(
        lambda request: httpx.Response(200, json=session(remote._now() + 86400))
    )
    assert await provider.verify_token(TOKEN)


def test_http_validation_outage_returns_503_not_invalid_token(mock_http):
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider, remote._now() + 86400)
    mock_http(lambda request: httpx.Response(503))
    server = FastMCP("auth-test", auth=provider)
    with TestClient(server.http_app(path="/")) as client:
        response = client.get("/", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 503
        assert response.json() == {"error": "temporarily_unavailable"}
        assert response.headers["Retry-After"] == "60"
        assert "WWW-Authenticate" not in response.headers
        assert provider._store.get_connection(TOKEN).state == "active"
        response = client.get("/", headers={"Authorization": "Bearer unknown"})
        assert response.status_code == 401
        mock_http(
            lambda request: httpx.Response(
                200, json=session(remote._now() + 86400)
            )
        )
        response = client.get(
            "/.well-known/oauth-authorization-server",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_unchanged_session_expiry_does_not_write_sqlite(
    monkeypatch, mock_http
):
    monkeypatch.setattr(remote, "_now", lambda: 1000)
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider, 86400)
    mock_http(lambda request: httpx.Response(200, json=session(86400)))

    def unexpected_write(*args):
        raise AssertionError("Unchanged expiry must not be written again")

    monkeypatch.setattr(provider._store, "update_expiry", unexpected_write)
    await provider._maintain_sessions()
    assert await provider.verify_token(TOKEN)


@pytest.mark.asyncio
async def test_missing_session_during_extension_stops_maintenance(
    monkeypatch, mock_http
):
    monkeypatch.setattr(remote, "_now", lambda: 1000)
    provider = ConnhexOAuthProvider(make_settings())
    add_connection(provider)
    mock_http(
        lambda request: (
            httpx.Response(404)
            if request.method == "PATCH"
            else httpx.Response(200, json=session(2000))
        )
    )
    await provider._maintain_sessions()
    assert provider._store.get_connection(TOKEN).state == "invalid"


@pytest.mark.asyncio
async def test_login_does_not_retain_credentials(mock_http):
    provider = ConnhexOAuthProvider(make_settings())
    oauth_client = make_oauth_client()
    await provider.register_client(oauth_client)

    def handler(request):
        if request.method == "POST":
            assert b"user-password" in request.content
            return httpx.Response(200, json={"session_token": TOKEN})
        return httpx.Response(
            200,
            json={
                "ui": {
                    "action": "https://accounts.compiuta.connhex.dev/auth/self-service/login"
                },
            },
        )

    mock_http(handler)
    with TestClient(Starlette(routes=provider.get_routes("/"))) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": "client-1",
                "redirect_uri": "https://chatgpt.com/connector/oauth/test",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        from urllib.parse import urlparse, parse_qs

        flow_id = parse_qs(urlparse(response.headers["location"]).query)[
            "flow_id"
        ][0]
        response = client.post(
            "/oauth/login",
            data={
                "flow_id": flow_id,
                "identifier": "private@example.com",
                "password": "user-password",
            },
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert not provider._pending_flows
    assert "user-password" not in repr(provider.__dict__)
    assert "private@example.com" not in repr(provider.__dict__)
    with sqlite3.connect(provider.settings.oauth_client_store_path) as conn:
        assert not conn.execute("SELECT * FROM oauth_connections").fetchall()
        payload = str(conn.execute("SELECT * FROM oauth_clients").fetchall())
    assert "user-password" not in payload
    assert "private@example.com" not in payload


@pytest.mark.asyncio
async def test_another_client_cannot_revoke_connection(mock_http):
    provider = ConnhexOAuthProvider(make_settings())
    await provider.register_client(make_oauth_client("other-client"))
    add_connection(provider, remote._now() + 86400)
    mock_http(
        lambda request: httpx.Response(200, json=session(remote._now() + 86400))
    )
    with TestClient(Starlette(routes=provider.get_routes("/"))) as client:
        response = client.post(
            "/revoke",
            data={
                "token": TOKEN,
                "client_id": "other-client",
                "client_secret": "client-secret",
                "token_type_hint": "access_token",
            },
        )
    assert response.status_code == 200
    assert provider._store.get_connection(TOKEN).state == "active"
