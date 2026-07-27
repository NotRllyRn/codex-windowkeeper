# Security policy

Do not report secrets in public issues. Send suspected credential exposure,
OAuth callback bypasses, vault failures, activation duplication, or
managed-Codex boundary bypasses privately to the repository maintainers.

Before reporting, retain only sanitized operation IDs, timestamps, and error
codes. Never attach `auth.json`, callback URLs, device codes, vault keys,
administrator passwords, SQLite files, raw runtime directories, or unsanitized
logs.

Windowkeeper does not enforce browser request origins; operators must restrict
network access themselves. CSRF tokens remain enforced. Downloading the latest
`auth.json` requires an authenticated session, CSRF validation, administrator
password reauthentication, and returns a non-cacheable attachment. Manually
pasted source tokens remain in memory only until Codex refreshes them and are
never stored directly. Refresh replaces the local downloadable bundle but does
not revoke files downloaded earlier.

Webhook notifications are redacted before durable storage and never contain
credentials. They do contain operational account metadata, including display
name and authenticated email, to identify affected accounts. Configure only
trusted HTTPS destinations.

Treat downloaded credential files like passwords and move them directly into
protected credential storage. Windowkeeper's security boundary assumes a
trusted host and the Codex executable managed by its release image. A
compromised host, root user, or malicious child binary is outside that
boundary.
