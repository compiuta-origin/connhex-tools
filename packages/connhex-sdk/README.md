# Connhex SDK

Internal async Python client for the Connhex API.

## What it provides

- Authentication (Connhex Accounts password login, bearer token, session forwarding)
- Per-domain async service classes: `ThingsService`, `ModelsService`, `ReaderService`, `ResourcesService`, `RulesEngineService`, `IAMService`, ...
- Pydantic models for all API responses
- A shared `ConnhexClient` that handles auth resolution and HTTP retries

## Instance URL

SDK clients target the Connhex SaaS instance at `https://connhex.com` by default:

```python
from connhex import AsyncConnhex

async with AsyncConnhex(token="YOUR_SESSION_TOKEN") as connhex:
    me = await connhex.iam.whoami()
```

Override the instance URL for staging, private, or self-hosted deployments:

```python
from connhex import Connhex

with Connhex(
    instance_url="https://staging.connhex.example",
    token="YOUR_SESSION_TOKEN",
) as connhex:
    things = connhex.things.list()
```

Precedence is: explicit `instance_url`, then `CONNHEX_INSTANCE_URL`, then `https://connhex.com`.

## Identities

Both `AsyncConnhex` and `Connhex` expose Connhex identity reads through `iam`:

```python
async with AsyncConnhex(token="YOUR_SESSION_TOKEN") as connhex:
    identity = await connhex.iam.get_identity("identity-uuid")
    page = await connhex.iam.list_identities(limit=20, offset=0)
    if page.has_more:
        next_page = await connhex.iam.list_identities(
            limit=20, offset=page.next_offset
        )
    matches = await connhex.iam.list_identities(
        credentials_identifier="user@example.com"
    )
```

`IdentitiesPage` contains `identities`, `limit`, `offset`, `has_more`, and
`next_offset` (null at the end). Credential information is excluded from
both get and list results. Traits and metadata support tenant-specific schemas.
The authenticated principal must have permission to read identities.

Pagination cursors remain internal: each call scans from the first page, so high
offsets require additional HTTP requests. Pagination is not a snapshot when
identities change concurrently. Invalid payloads or pagination continuations
raise `InvalidResponseError`; HTTP failures retain the SDK's usual errors.
