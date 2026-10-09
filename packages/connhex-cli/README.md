# Connhex CLI

A command-line interface for [Connhex](https://connhex.com) that lets you read Connhex identities and manage connectables, things, models, resources, rules, and IoT messages from the terminal.

## Installation

### With uv (recommended for development)

```bash
uv tool install git+https://github.com/compiuta-origin/connhex-tools#subdirectory=packages/connhex-cli
```

This installs the `connhex-cli` binary into uv's tool environment and makes it available on your `PATH`.

To update:

```bash
uv tool upgrade connhex-cli
```

### With pip

```bash
pip install git+https://github.com/compiuta-origin/connhex-tools#subdirectory=packages/connhex-cli
```

### From a workspace clone

```bash
git clone https://github.com/compiuta-origin/connhex-tools.git
cd connhex-tools
uv sync
```

Then run via `uv run connhex-cli` or activate the venv and use `connhex-cli` directly.

## Authentication

### Interactive login (default)

```bash
connhex-cli auth login
```

Prompts for your instance URL, username, and password. The instance URL defaults to Connhex SaaS at `https://connhex.com`; edit it to connect to an enterprise dedicated instance. On success the session token is cached at `~/.connhex/credentials.json` (mode `0600`). All subsequent commands reuse it until it expires.

```bash
connhex-cli auth status   # show cached token info without hitting the network
connhex-cli auth whoami   # verify the session against the API
connhex-cli auth logout   # delete the cached credentials
```

### Token (CI / scripts)

Pass a bearer token directly — no `login` required:

```bash
connhex-cli --token YOUR_SESSION_TOKEN things list
# or
CONNHEX_BEARER_TOKEN=YOUR_SESSION_TOKEN connhex-cli things list
```

When `--token` / `CONNHEX_BEARER_TOKEN` is set the credential store is ignored entirely.
Commands target `https://connhex.com` by default unless you pass an instance URL override.

### Instance URL

The instance URL defaults to `https://connhex.com`. `login` saves the URL you use and reuses it automatically. You can override it per-command:

```bash
connhex-cli --instance-url https://staging.connhex.example things list
# or
CONNHEX_INSTANCE_URL=https://staging.connhex.example connhex-cli things list
```

## Global options

These options must be placed **before** the subcommand:

```
connhex-cli [OPTIONS] COMMAND [ARGS]...

  --instance-url TEXT   Connhex instance URL  [env: CONNHEX_INSTANCE_URL]
  --token TEXT          Bearer token          [env: CONNHEX_BEARER_TOKEN]
  --output, -o TEXT     Output format: json (default) or table
  --log-config TEXT     Path to a JSON logging config file  [env: CONNHEX_LOG_CONFIG]
  --version             Print version and exit
```

## Output formats

Default output is machine-readable JSON. Add `--output table` (before the subcommand) for a Rich table (or panel for single objects):

```bash
connhex-cli --output table things list --limit 5
connhex-cli --output table things get <id>
```

## Commands

### auth

| Command       | Description                              |
| ------------- | ---------------------------------------- |
| `auth login`  | Log in and cache a session token         |
| `auth logout` | Delete cached credentials                |
| `auth whoami` | Show current user info (network call)    |
| `auth status` | Show cached credential info (local only) |

### identities

Read Connhex identities using the existing authentication configuration.

| Command               | Description                                           |
| --------------------- | ----------------------------------------------------- |
| `identities list`     | List Connhex identities with filtering and pagination |
| `identities get <id>` | Get a single Connhex identity by UUID                 |

List options:

```text
--limit INTEGER                 Max identities to return (positive) [default: 50]
--offset INTEGER                Identities to skip (non-negative)  [default: 0]
--credentials-identifier TEXT   Exact credential identifier (email or username)
```

JSON lists include `identities`, `limit`, `offset`, `has_more`, and `next_offset`
(`null` at the end). Use the returned `next_offset` with `--offset` to continue.
Table output shows the identities and the next offset when more results exist.

```bash
connhex-cli identities list --limit 20 --offset 0
connhex-cli identities list --credentials-identifier user@example.com
connhex-cli identities get <identity-id>
connhex-cli --output table identities list --limit 20
```

### connectables

Bulk-register devices end-to-end: provision API + manufacturing record, with rollback on failure.

| Command                        | Description                                               |
| ------------------------------ | --------------------------------------------------------- |
| `connectables register <file>` | Bulk-register devices from a CSV/JSON file (or `-` stdin) |

Flags:

```
--format csv|json             Required when reading from stdin (- )
--schema <name>               Manufacturing resource type        [default: device]
--serial-number-field <name>  Manufacturing field auto-filled
                              with provision.init_id             [default: serial_number]
--connhex-id-field <name>     Manufacturing field auto-filled
                              with the provisioned thing ID      [default: connhex_id]
```

Input format (CSV columns or flat JSON keys):

```
provision.init_id            (required) external identifier
provision.init_key           external key (auto-generated UUID if omitted)
provision.name               human-readable name
provision.model              UUID of the device model
provision.migration_key
provision.migration_key_quota
manufacturing.<field>        any attribute in --schema (snake_case
                             is auto-normalized to camelCase)
tenant                       optional tenant id
```

JSON may also use the nested shape: `[{"provision": {...}, "manufacturing": {...}, "tenant": "..."}]`.

The command pre-validates the batch against the manufacturing schema (unknown fields, duplicate `init_id`/`init_key`, missing `init_id`, non-UUID `model`) before any API call. If the manufacturing step fails for any row, all provisioned things from that run are deleted.

Examples:

```bash
connhex-cli connectables register ./devices.csv
connhex-cli connectables register ./devices.json --schema sensors
cat devices.json | connhex-cli connectables register - --format json
echo '[{"provision":{"init_id":"SN1"},"manufacturing":{"device_type":"rpi"}}]' \
  | connhex-cli connectables register - --format json
```

### things

| Command                                    | Description                                        |
| ------------------------------------------ | -------------------------------------------------- |
| `things list`                              | List things with optional filtering and pagination |
| `things get <id>`                          | Get a single thing by ID                           |
| `things status <id>...`                    | Connectivity status for one or more things         |
| `things status-summary`                    | Fleet-wide connectivity summary                    |
| `things flapping`                          | List devices with excessive reconnections          |
| `things uptime <id> --from <ts> --to <ts>` | Uptime and connect/disconnect timeline             |
| `things channels <id>`                     | List channels connected to a thing                 |

### models

| Command              | Description                     |
| -------------------- | ------------------------------- |
| `models list`        | List device models              |
| `models get <id>`    | Get a device model by ID        |
| `models things <id>` | List things assigned to a model |

### resources / manufacturing

Both services share the same command shape. Append `--manufacturing` / `-m` to target the manufacturing service instead.

| Command                                     | Description                    |
| ------------------------------------------- | ------------------------------ |
| `resources list <type>`                     | List resources of a given type |
| `resources get <type> <id>`                 | Get a resource by ID           |
| `resources create <type> <attrs-json>`      | Create a resource              |
| `resources update <type> <id> <attrs-json>` | Update a resource              |
| `resources delete <type> <id>`              | Delete a resource              |

### rules

| Command                            | Description      |
| ---------------------------------- | ---------------- |
| `rules list`                       | List rules       |
| `rules get <id>`                   | Get a rule by ID |
| `rules create <payload-json>`      | Create a rule    |
| `rules update <id> <payload-json>` | Update a rule    |
| `rules delete <id>`                | Delete a rule    |
| `rules events [<rule-id>]`         | List rule events |

### messages

| Command                 | Description                                                       |
| ----------------------- | ----------------------------------------------------------------- |
| `messages channel <id>` | Read messages from a channel                                      |
| `messages thing <id>`   | Read messages for a thing (resolves events channel automatically) |

## Usage examples

```bash
# Log in
connhex-cli auth login

# List the first 10 things
connhex-cli things list --limit 10

# Get a thing, output as JSON
connhex-cli --output json things get c4a50e4e-78ba-4469-bab1-e8b3f88f3c95

# Fleet connectivity at a glance
connhex-cli things status-summary

# Check uptime over the last 7 days (Unix timestamps)
connhex-cli things uptime <id> --from $(date -d '7 days ago' +%s) --to $(date +%s)

# Read the last 20 messages from a thing
connhex-cli messages thing <thing-id> --limit 20

# Read messages between two timestamps
connhex-cli messages channel <channel-id> --from 1778400000 --to 1778500000

# List resources of type "devices"
connhex-cli resources list devices

# List manufacturing resources
connhex-cli resources list batches --manufacturing

# CI usage with a token (no login required)
CONNHEX_BEARER_TOKEN=YOUR_SESSION_TOKEN connhex-cli --output json things list

# Bulk-register a batch of devices from a CSV
connhex-cli connectables register ./fleet.csv
```

## Logging

By default only warnings and errors are printed to stderr. To enable debug output, supply a JSON logging config file:

```bash
connhex-cli --log-config ./debug-logging.json things list
# or
CONNHEX_LOG_CONFIG=./debug-logging.json connhex-cli things list
```

Example `debug-logging.json`:

```json
{
  "version": 1,
  "disable_existing_loggers": false,
  "handlers": {
    "stderr": {
      "class": "logging.StreamHandler",
      "stream": "ext://sys.stderr"
    }
  },
  "root": {
    "level": "DEBUG",
    "handlers": ["stderr"]
  }
}
```

## Development

```bash
git clone https://github.com/compiuta-origin/connhex-tools.git
cd connhex-tools
uv sync

uv run pytest packages/connhex-cli/tests
uv run ruff check packages/connhex-cli/
```
