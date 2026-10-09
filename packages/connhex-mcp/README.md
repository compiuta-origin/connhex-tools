# Connhex MCP Server

An MCP server that exposes [Connhex](https://connhex.com) APIs as tools.

## Setup

### Remote MCP Server

Connhex provides a hosted remote MCP server for the SaaS instance:

```text
https://mcp.connhex.com
```

The remote MCP server handles authentication through your browser. When you
first connect, your MCP client will prompt you to authenticate with your
Connhex account.

Remote deployments should persist OAuth client registrations and encrypted
Connhex sessions so MCP clients can reuse their connection after a server
restart or image update. Set `CONNHEX_OAUTH_CLIENT_STORE_PATH` to a SQLite file
on a persistent volume, for example `/data/oauth-clients.sqlite`, and provide
a stable Fernet key through `CONNHEX_OAUTH_SESSION_ENCRYPTION_KEY`. Configure
`CONNHEX_KRATOS_ADMIN_URL` with the Kratos admin endpoint for automatic session
extension. Login credentials are not stored.

| Deployment                     | MCP server URL                                                                   | Authentication                         |
| ------------------------------ | -------------------------------------------------------------------------------- | -------------------------------------- |
| Connhex SaaS                   | `https://mcp.connhex.com`                                                        | Connhex SaaS account via browser OAuth |
| Local MCP targeting SaaS       | Local `uvx` server, no `CONNHEX_INSTANCE_URL` needed                             | Local env vars                         |
| Local MCP targeting enterprise | Local `uvx` server with `CONNHEX_INSTANCE_URL=https://<customer-connhex-domain>` | Local env vars                         |

### Configuration with well-known MCP clients

#### Claude Code

Run the following command to add the Connhex MCP server:

```bash
claude mcp add connhex --transport http https://mcp.connhex.com
```

Then use the `/mcp` slash command inside Claude Code to authenticate with your
Connhex account. This opens a browser window where you can complete the login
process.

Use `-s user` or `-s local` if you want to control whether Claude Code stores
the server globally or only for the current project.

#### Codex

Run the following commands to add the Connhex MCP server and authenticate:

```bash
codex mcp add connhex --url https://mcp.connhex.com
codex mcp login connhex
```

`codex mcp login connhex` prints an authorization URL. Open it in your browser,
sign in with your Connhex account, then return to Codex. Start a new Codex
conversation after login so MCP tools reload.

You can also configure the server directly in `~/.codex/config.toml`:

```toml
[mcp_servers.connhex]
url = "https://mcp.connhex.com"
```

Then run:

```bash
codex mcp login connhex
```

#### Claude Desktop and JSON clients

If your MCP client uses JSON configuration, add this server definition:

```json
{
  "mcpServers": {
    "connhex": {
      "type": "http",
      "url": "https://mcp.connhex.com"
    }
  }
}
```

### Running Locally

Use a local stdio MCP server when your client cannot use remote MCP, when you
need token-based auth in a browserless environment, or when developing the MCP
server.

#### Prerequisites

- Python 3.11+
- [uvx](https://docs.astral.sh/uv/getting-started/installation/)
- A Connhex account with access to the target instance

The local server connects to the Connhex SaaS instance at `https://connhex.com`
by default. Set `CONNHEX_INSTANCE_URL` only when targeting an enterprise
dedicated, staging, private, or self-hosted Connhex API instance.

#### Claude Code local stdio

```bash
claude mcp add -s user connhex \
  -e CONNHEX_USERNAME=your-email@example.com \
  -e CONNHEX_PASSWORD=your-password \
  -- \
  uvx --from git+https://github.com/compiuta-origin/connhex-tools connhex-mcp
```

For an enterprise/custom-domain Connhex API instance, add:

```bash
-e CONNHEX_INSTANCE_URL=https://<customer-connhex-domain>
```

#### Codex local stdio

```bash
codex mcp add connhex \
  --env CONNHEX_USERNAME=your-email@example.com \
  --env CONNHEX_PASSWORD=your-password \
  -- \
  uvx --from git+https://github.com/compiuta-origin/connhex-tools connhex-mcp
```

For an enterprise/custom-domain Connhex API instance, add:

```bash
--env CONNHEX_INSTANCE_URL=https://<customer-connhex-domain>
```

Codex stores MCP servers in `~/.codex/config.toml` by default. You can also add
the same server to a trusted project-scoped `.codex/config.toml`.

#### JSON clients local stdio

```json
{
  "mcpServers": {
    "connhex": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/compiuta-origin/connhex-tools",
        "connhex-mcp"
      ],
      "env": {
        "CONNHEX_USERNAME": "your-email@example.com",
        "CONNHEX_PASSWORD": "your-password"
      }
    }
  }
}
```

Add `CONNHEX_INSTANCE_URL` under `env` when targeting an enterprise/custom
Connhex API instance.

### Local Authentication

Local authentication is inferred from the environment variables available to
the `connhex-mcp` process:

| Environment variables                                        | Description                                                                  |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `CONNHEX_USERNAME`, `CONNHEX_PASSWORD`                       | Logs in with username and password, then caches the session token in memory. |
| `CONNHEX_BEARER_TOKEN`                                       | Uses a static bearer token.                                                  |
| `CONNHEX_SESSION_COOKIE`                                     | Uses a static `chx_auth_session` cookie value.                               |
| Incoming `Authorization` header or `chx_auth_session` cookie | Used when the MCP transport forwards request headers.                        |

Session-cookie authentication is sent directly to Connhex as
`Cookie: chx_auth_session=<value>`; it does not require a Kratos JWT token
template. Set `CONNHEX_SESSION_COOKIE` to the cookie value only, not a full
`Cookie` header.

For sandboxed or browserless environments, use token-based auth with the local
stdio server:

```bash
CONNHEX_BEARER_TOKEN=your-token
```

For Claude Code local stdio:

```bash
claude mcp add -s user connhex \
  -e CONNHEX_BEARER_TOKEN=your-token \
  -- \
  uvx --from git+https://github.com/compiuta-origin/connhex-tools connhex-mcp
```

For Codex local stdio:

```bash
codex mcp add connhex \
  --env CONNHEX_BEARER_TOKEN=your-token \
  -- \
  uvx --from git+https://github.com/compiuta-origin/connhex-tools connhex-mcp
```

### Local Transport

By default the server uses `stdio`. You can select a different transport by appending `--transport` to the `args` array:

```json
"args": [
  "--from",
  "git+https://github.com/compiuta-origin/connhex-tools",
  "connhex-mcp",
  "--transport",
  "streamable-http"
]
```

Available transports: `stdio`, `http`, `sse`, `streamable-http`.

### Tool Customization

Deployments can hide tools with `CONNHEX_DISABLED_TOOLS`, a comma-separated
list of tool names.

Deployments can also override tool descriptions and titles with
`CONNHEX_TOOL_TRANSFORMS`. The value must be a JSON object keyed by existing
tool name:

```json
{
  "read_thing_messages": {
    "description": "Read deployment-specific telemetry for a Connhex thing.",
    "title": "Read Thing Telemetry"
  },
  "list_things": {
    "description": "List Connhex things visible in this deployment."
  }
}
```

## Updating

`uvx` caches the built environment on first run and does **not** re-fetch the git repo on subsequent invocations, so updates to this server are not picked up automatically. To pull the latest version, run:

```bash
uvx --refresh --from git+https://github.com/compiuta-origin/connhex-tools connhex-mcp
```

Then restart your MCP client.

## Available Tools

### IAM

| Tool              | Description                                                                    |
| ----------------- | ------------------------------------------------------------------------------ |
| `whoami`          | Return information about the currently authenticated user.                     |
| `list_identities` | List Connhex identities with exact email or username filtering and pagination. |
| `get_identity`    | Read a Connhex identity by UUID.                                               |

`get_identity(identity_id)` and
`list_identities(limit=10, offset=0, credentials_identifier=None)` are read-only
tools. `limit` must be positive and `offset` non-negative; the optional
`credentials_identifier` filter matches an exact email or username.

Both identity tools exclude credential information and use the existing
authentication and tool filtering settings. The authenticated principal needs
identity read permissions. List results include `identities`, `limit`, `offset`,
`has_more`, and `next_offset` (`null` at the end). Pass `next_offset` as `offset`
to continue; no pagination cursor is exposed. High offsets require additional
HTTP requests, and concurrent identity changes can affect pagination.

### Resources (JSON:API)

Generic CRUD over the Connhex resources service.

| Tool              | Description                                                                                                        |
| ----------------- | ------------------------------------------------------------------------------------------------------------------ |
| `list_resources`  | List resources of a given type, with filtering, sorting, sparse fieldsets, and pagination.                         |
| `get_resource`    | Get a specific resource by ID.                                                                                     |
| `create_resource` | Create a new resource.                                                                                             |
| `update_resource` | Partially update an existing resource.                                                                             |
| `delete_resource` | Delete a resource (irreversible).                                                                                  |
| `get_schema`      | Discover valid resource types, attributes, and relationships across both the resources and manufacturing services. |

### Manufacturing (JSON:API)

Same CRUD shape as Resources, against the manufacturing service.

| Tool                            | Description                                     |
| ------------------------------- | ----------------------------------------------- |
| `list_manufacturing_resources`  | List manufacturing resources.                   |
| `get_manufacturing_resource`    | Get a manufacturing resource by ID.             |
| `create_manufacturing_resource` | Create a manufacturing resource.                |
| `update_manufacturing_resource` | Partially update a manufacturing resource.      |
| `delete_manufacturing_resource` | Delete a manufacturing resource (irreversible). |

### Reader (IoT messages)

Read messages from Connhex IoT channels. Supports the four CMP components (`messages`, `params`, `infos`, `metrics`) and decimation/aggregation for SenML formats.

| Tool                    | Description                                                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------------------------------ |
| `read_channel_messages` | Read messages from a channel by its channel ID.                                                              |
| `read_thing_messages`   | Read messages for a thing (device/edge) by its thing ID (resolves the channel ID from the thing's metadata). |

### Things

Manage IoT things (devices and edges) and inspect their connectivity.

| Tool                        | Description                                                                          |
| --------------------------- | ------------------------------------------------------------------------------------ |
| `get_thing`                 | Get a single thing by ID, including its typed metadata (channels, device type...).   |
| `list_things`               | List things with optional name filter and pagination.                                |
| `get_things_status`         | Get current connectivity status for a batch of things by their IDs.                  |
| `get_things_status_summary` | Fleet-wide connectivity summary: online, offline, never connected, active last hour. |
| `get_things_flapping`       | List devices with an excessive number of reconnections within a time window.         |
| `get_thing_uptime`          | Connect/disconnect timeline and total uptime for a single thing in a time range.     |
| `get_thing_channels`        | List the channels connected to a specific thing.                                     |

### Models

Manage device models and browse the things assigned to them.

| Tool               | Description                                              |
| ------------------ | -------------------------------------------------------- |
| `get_model`        | Get a single device model by ID.                         |
| `list_models`      | List models with optional name, tag, and tenant filters. |
| `get_model_things` | List all things assigned to a specific device model.     |

### Rules Engine

Manage rules and inspect triggered rule events.

| Tool               | Description                                    |
| ------------------ | ---------------------------------------------- |
| `list_rules`       | List rules, with filtering and pagination.     |
| `get_rule`         | Get a single rule by ID.                       |
| `create_rule`      | Create a new rule.                             |
| `update_rule`      | Partially update an existing rule.             |
| `delete_rule`      | Delete a rule (irreversible).                  |
| `list_rule_events` | List rule events (triggered rule occurrences). |

## Usage Examples

**IAM and Connhex identities**

- "Who am I logged in as?"
- "List the first 20 Connhex identities."
- "Find the Connhex identity with the exact email `user@example.com`."
- "Get Connhex identity `<identity-id>`."

**Discover the data model**

- "What resource types are available in this Connhex instance?"
- "What attributes does the `devices` resource type have?"

**Browse and search resources**

- "List all my devices."
- "Find devices whose serial starts with `ABC`."
- "Show me plants created in the last week."
- "Get device `<device-id>` and include its related site."
- "List the 50 most recently created devices, only showing `serial` and `name`."

**Create / update / delete resources**

- "Create a new installation called `Installation A`."
- "Update device `<device-id>` to set its name to `Boiler 3`."
- "Delete installation `<installation-id>`."

**Manufacturing**

- "List all manufacturing batches."

**IoT messages (telemetry)**

- "Show me the last 10 messages from thing `<thing-id>`."
- "Read messages from channel `<channel-id>` between yesterday and today."
- "Show me the daily max CPU usage (metrics) for device `<connhex-id>` this week."
- "Filter messages from channel `<channel-id>` to only the `temperature` SenML name."

**Things**

- "List all things in this instance."
- "Get thing `<thing-id>` and show me its event and control channel IDs."
- "How many devices are currently online?"
- "Are there any devices that are reconnecting excessively?"
- "Show me the connectivity timeline for device `<thing-id>` over the last 7 days."
- "What channels is thing `<thing-id>` connected to?"

**Models**

- "List all device models."
- "Show me all things assigned to model `<model-id>`."
- "Which model does thing `<thing-id>` use?"

**Rules Engine**

- "List all enabled rules with severity `critical`."
- "Show me rule `<rule-id>`."
- "Disable rule `<rule-id>`."
- "Show me all rule events from the last 24 hours."
- "List events triggered by rule `<rule-id>` between `<from>` and `<to>`."

## Testing with MCP Inspector

You can test the server locally using [MCP Inspector](https://github.com/modelcontextprotocol/inspector) (requires Node.js):

```bash
export CONNHEX_USERNAME=your-email@example.com
export CONNHEX_PASSWORD=your-password
./scripts/start-mcp-inspector.sh
```

For token-based auth:

```bash
export CONNHEX_AUTH_TYPE=token
export CONNHEX_BEARER_TOKEN=your-token
./scripts/start-mcp-inspector.sh
```

This opens a browser UI where you can interactively call tools and inspect responses.

## Development

Clone the repo and install dependencies:

```bash
git clone https://github.com/compiuta-origin/connhex-tools.git
cd connhex-tools
uv sync --dev
```

Run the server locally:

```bash
uv run connhex-mcp
```

Run tests and linting:

```bash
uv run pytest
uv run ruff check .
```

## Privacy Policy

The Connhex MCP Server acts as a proxy between AI clients and a Connhex instance. It does not collect, store, or process data on its own behalf.

**Data handling:** All requests are forwarded exclusively to the configured Connhex instance URL, defaulting to `https://connhex.com`. Set `CONNHEX_INSTANCE_URL` to target a different Connhex deployment. No data is sent to any other third party.

**Third-party services:** The server communicates only with the configured Connhex instance. No analytics, telemetry, or tracking services are used.

**Contact:** For privacy-related inquiries, contact [info@compiuta.com](mailto:info@compiuta.com).

- Full privacy policy: [https://connhex.com/legal/platform-privacy-notice](https://connhex.com/legal/platform-privacy-notice)
- Terms and Conditions: [https://connhex.com/legal/terms-and-conditions](https://connhex.com/legal/terms-and-conditions)
- Acceptable Use Policy: [https://connhex.com/legal/acceptable-use-policy](https://connhex.com/legal/acceptable-use-policy)
