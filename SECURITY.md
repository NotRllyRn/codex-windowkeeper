# Security policy

Do not report secrets in public issues. Send suspected credential exposure, OAuth callback bypasses, vault failures, activation duplication, or managed-Codex boundary bypasses privately to the repository maintainers.

Before reporting, retain only sanitized operation IDs, timestamps, and error codes. Never attach `auth.json`, callback URLs, device codes, vault keys, administrator passwords, SQLite files, raw runtime directories, or unsanitized logs.

Windowkeeper's security boundary assumes a trusted host and the Codex executable managed by its release image. A compromised host, root user, or malicious child binary is outside that boundary.
