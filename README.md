# Codex Windowkeeper

Windowkeeper is a single-instance supervisor for independently authenticated ChatGPT/Codex accounts. It reads authoritative short and weekly usage windows from the pinned Codex app-server, schedules one evidence-backed activation per reset window, and makes ambiguous submissions visible instead of retrying blindly.

## What ships

- Isolated runtime and encrypted credential lineage per account.
- Device-code sign-in (recommended) and managed browser OAuth with strict callback validation.
- Confirmed, estimated, and unknown scheduling states; manual activation uses the same deduplication path.
- Five switchable dashboard compositions—Orbit, Ledger, Rail, Timeline, and Focus—in light and dark themes.
- Durable operations, incidents, SSE updates, sanitized JSONL logs, and generic/Slack/Discord webhooks.
- SQLite, AES-256-GCM, opaque administrator sessions, CSRF, recent-password confirmation, and fail-closed Codex compatibility checks.

Windowkeeper does **not** pool quota, route work between accounts, expose a public API, or call undocumented usage endpoints.

## Local development

Requires Python 3.12+, `uv`, and a separately installed Codex executable.

```bash
uv sync --all-extras
uv run ruff check src tests
uv run mypy src tests
uv run pytest
```

Initialize protected key/password files without putting secrets in shell history:

```bash
windowkeeper init --key-file /secure/windowkeeper.key
# or set WINDOWKEEPER_ADMIN_PASSWORD_FILE to a mode-0600 file
```

A service is ready only when the vault is configured and the observed Codex `--version` output and executable SHA-256 exactly equal `WINDOWKEEPER_CODEX_VERSION` and `WINDOWKEEPER_CODEX_SHA256`.

## Hardened Docker Compose

1. Pin the validated Codex npm package release, observed version output, and executable digest.
2. Create files containing a generated `wk1_...` vault key and a 15+ character administrator password. Generate the key with `windowkeeper vault generate-key --output /secure/windowkeeper.key`. For local Docker Compose implementations that preserve source-file ownership, make both files mode `0600` and readable by container UID/GID `10001:10001`.
3. Bind to loopback or a trusted LAN interface only.

```bash
export WINDOWKEEPER_CODEX_PACKAGE_VERSION='<validated npm version>'
export WINDOWKEEPER_CODEX_VERSION='<exact codex --version output>'
export WINDOWKEEPER_CODEX_SHA256='<sha256 of /usr/local/bin/codex in the image>'
export WINDOWKEEPER_VAULT_KEY_FILE="$PWD/secrets/vault.key"
export WINDOWKEEPER_ADMIN_PASSWORD_FILE="$PWD/secrets/admin-password"
export WINDOWKEEPER_BIND_ADDRESS=127.0.0.1
docker compose up --build -d
```

The image runs as UID 10001 with a read-only root filesystem, dropped capabilities, no-new-privileges, bounded tmpfs runtime trees, and a persistent `/data` volume. `/health/live` checks the process; `/health/ready` also requires the vault and exact Codex compatibility tuple.

### OAuth deployment modes

- `manual` (default): device code works from Docker/NAS/SSH. Browser sign-in displays a one-time authorization URL, then securely accepts the exact localhost callback URL in the authenticated UI. OAuth query values are never persisted or logged.
- `host-loopback`: Linux-only automatic browser callback mode. Start with `docker compose -f compose.host-network.yaml up --build`; keep the service bound to loopback or behind a trusted reverse proxy.
- `disabled`: browser login is unavailable; device code remains available.

Only one browser attempt may own the callback-port set. Device-code attempts remain isolated and obey the configured authentication concurrency bound.

## Operations

See [OPERATIONS.md](OPERATIONS.md) for initialization, OAuth modes, backup/restore, reverse-proxy configuration, incident response, upgrades, and rollback. Release operators must also complete [RELEASE_GATES.md](RELEASE_GATES.md).

```bash
windowkeeper --version
windowkeeper version --json
windowkeeper health --json
windowkeeper status --json
windowkeeper doctor
windowkeeper backup --output /secure/backups/windowkeeper.sqlite
windowkeeper restore --input /secure/backups/windowkeeper.sqlite --confirm RESTORE
windowkeeper vault rotate --old-key-file /secure/old.key --new-key-file /secure/new.key
windowkeeper password-set
windowkeeper vault verify --key-file /secure/current.key
```

Vault rotation is offline, all-or-nothing, and re-encrypts active credentials plus webhook URLs/signing secrets before writing the new key file. Replace the configured key file atomically only after the command succeeds.

The dashboard provides account enable/disable, reauthentication, typed-confirmation deletion, manual refresh/activation, operation history, incident state, webhook management, log filtering, and sanitized JSONL download. Destructive or secret-changing actions require CSRF and recent administrator password verification.

## Security boundary

The vault key must not live in SQLite or the persistent data directory. Runtime credential files exist only under the runtime tmpfs and are removed when the account process stops. URL query strings, callback values, device codes, tokens, authorization headers, and known token-shaped strings are redacted before logs, SSE, API responses, incidents, or webhooks.

Windowkeeper trusts the pinned Codex child process with plaintext credentials while that isolated process is running. It does not protect against a compromised host, root user, or malicious validated Codex binary.

## UI evaluation

Use the **View** selector in the header to switch among all five mockups without losing filters. Use the adjacent theme control for system, light, or dark mode. Both choices are stored locally in the browser; the server view-model and functionality remain identical.
