# Windowkeeper operations

## Install and initialize

Windowkeeper requires Python 3.12+, a dedicated service account, SQLite storage on a local filesystem, and one exact Codex app-server release. Keep the persistent data directory and runtime directory separate; put the runtime directory on tmpfs.

```bash
uv sync --locked
windowkeeper init --key-file /secure/windowkeeper-vault.key
windowkeeper doctor
windowkeeper serve
```

`init` writes the key with mode `0600`, creates the vault sentinel, and prompts twice for the first administrator password. The key must remain outside the persistent data directory. For Docker Compose, both secret source files must be readable by container UID/GID `10001:10001`; some local Compose implementations do not apply the declared secret ownership to file-backed secrets. A service is not ready until `doctor` confirms the exact configured Codex version and executable SHA-256.

## Account sign-in

Device code is recommended for local, NAS, Docker, and SSH deployments. Browser OAuth supports three modes:

- `manual`: display the validated authorization URL and paste the resulting localhost callback URL into the authenticated UI.
- `host-loopback`: receive the validated localhost callback directly; only use on a Linux host where Windowkeeper owns the pinned callback ports.
- `disabled`: prohibit browser OAuth while retaining device-code sign-in.

Windowkeeper validates HTTPS, callback host/path/port, OAuth state, response size, and account/workspace identity before promoting credentials. Failed replacement credentials never replace the active bundle.

## Back up and restore

Stop Windowkeeper before all offline CLI operations.

```bash
windowkeeper backup --output /secure/backups/windowkeeper.sqlite
windowkeeper restore --input /secure/backups/windowkeeper.sqlite --confirm RESTORE
windowkeeper vault verify --key-file /secure/windowkeeper-vault.key
windowkeeper doctor
```

Backups contain encrypted credentials and webhook secrets but still contain account metadata; protect them as mode-`0600` files. Back up the vault key separately. Restore validates SQLite integrity and schema, replaces only the database, and never restores a key. Start the service only after key verification succeeds.

## Rotate the vault key

```bash
windowkeeper vault rotate \
  --old-key-file /secure/windowkeeper-vault.key \
  --new-key-file /secure/windowkeeper-vault.next
windowkeeper vault verify --key-file /secure/windowkeeper-vault.next
```

Rotation is offline and transactional. It re-encrypts active credentials, webhook URLs, webhook signing secrets, and the sentinel. Replace the configured key-file reference only after verification. Keep the old key in protected recovery storage until the new service has passed readiness and account refresh checks.

## Reverse proxy

Bind Windowkeeper to loopback or a private interface. Set `WINDOWKEEPER_PUBLIC_BASE_URL` to the externally visible HTTP(S) origin and `WINDOWKEEPER_TRUSTED_PROXIES` to an explicit comma-separated IP/CIDR allowlist. Wildcards are rejected. Use `WINDOWKEEPER_COOKIE_SECURE=true` for HTTPS. The proxy must preserve the configured root path, enforce request/body limits, and must not log query strings or request bodies. Do not expose Windowkeeper directly to the public internet.

## Incident response

1. Stop automatic activity by disabling the affected account.
2. Read the incident, operation history, and sanitized logs; retain IDs, timestamps, and error codes only.
3. For `authentication_failed`, reauthenticate and verify the same upstream account/workspace.
4. For `activation_ambiguous` or `activation_safety`, inspect upstream thread/turn evidence. Windowkeeper never retries that window. Use **Acknowledge without retry** only after review; this permits future windows, not the ambiguous one.
5. For compatibility failures, stop the service and re-run the official contract proof against the intended Codex release before updating both pins.
6. For suspected key or host compromise, stop the service, preserve encrypted evidence, rotate credentials outside Windowkeeper, rotate the vault key, and revoke administrator sessions by resetting the password.

Never attach credential files, callback URLs, device codes, vault keys, passwords, SQLite databases, runtime trees, or unsanitized logs to an issue.

## Upgrade and rollback

1. Stop the service and create a database backup.
2. Keep the old image/package, database backup, and vault key.
3. Validate the target Codex release; record exact version output and executable SHA-256.
4. Install the new Windowkeeper release and run `windowkeeper doctor`.
5. Start it and verify readiness, account refresh, incident state, and webhook delivery.
6. Roll back by stopping the service, restoring the matching backup, restoring the prior package/image and compatibility pins, verifying the vault key, and starting again.

Never downgrade a database to a release that does not support its schema.

## Security boundary

Windowkeeper protects credentials at rest, isolates runtime credential trees, redacts known secret-bearing values, and fails closed on compatibility drift. It cannot protect against root, a compromised host, or a malicious binary that already matches the operator-configured digest. The validated Codex child process necessarily receives plaintext credentials while its isolated runtime is active.
