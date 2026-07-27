# Manual token sign-in plan

## Outcome

Add **Paste tokens** beside device-code and browser sign-in. The administrator supplies an access token and refresh token; no timestamp is requested.

## Minimal flow

1. Validate that both token strings are present and reasonably bounded.
2. Build an in-memory Codex `auth.json` source using the access token as both the temporary ID-token JWT and bearer token, matching Codex's own external-access-token parsing strategy.
3. Pass that source through the existing two-way forced-refresh flow.
4. Let the pinned Codex app-server validate the refresh token, return canonical ID/access/refresh tokens, verify account/workspace identity, and create the managed and downloadable bundles atomically.
5. Store only the refreshed encrypted bundles. Never store, log, or echo the pasted source values.

Codex writes `last_refresh` during the immediate forced refresh, so an epoch timestamp field is unnecessary.

## UI and persistence

- Reveal two password-style fields only when **Paste tokens** is selected.
- Use the existing administrator-password and CSRF protections.
- Record `MANUAL_TOKENS` as the login method through a small SQLite migration.
- Send manual imports to the normal operation-progress page; browser and device-code methods retain the interactive OAuth progress page.

## Failure behavior

Invalid, expired, reused, mismatched, or non-refreshable tokens fail through the existing login operation and do not replace active credentials. Existing accounts retain their last good managed and downloadable bundles.
