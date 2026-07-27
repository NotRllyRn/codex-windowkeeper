# One-login dual-credential plan

## Outcome

The operator approves ChatGPT sign-in once. Windowkeeper immediately uses the resulting source refresh token twice within OpenAI's reuse grace period to create:

1. an encrypted managed credential bundle;
2. an encrypted downloadable credential bundle.

Every successful usage refresh repeats that two-way fork from the current managed bundle. Both replacements commit atomically, so the download always tracks the newest successful refresh and failures retain both prior bundles.

## Minimal design

- Add `refresh_token=True` to the existing Codex `account/read` adapter seam.
- Materialize the same source payload into two fresh, sequential isolated runtimes.
- Force one Codex-managed refresh in each runtime and capture each resulting `auth.json`.
- Verify that both refresh tokens rotated and both identities match.
- Replace `ACTIVE` and `EXPORT` in one SQLite transaction.
- Use the new managed payload for the current usage read and future activation.
- Keep the existing authenticated, CSRF-protected, password-confirmed download route.

No direct OAuth HTTP client, token parser domain model, refresh queue, or additional scheduler is introduced.

## Enrollment

1. Complete one browser or device-code sign-in.
2. Capture the source credential only in memory.
3. Fork it through two forced refreshes.
4. Commit the managed and downloadable outputs together.
5. Discard the source and temporary runtime homes.

Reauthentication follows the same one-sign-in process and replaces both outputs.

## Refresh

1. Decrypt the current managed bundle.
2. Fork it through two forced refreshes.
3. Read usage with the new managed runtime.
4. Atomically replace both bundles and commit usage.
5. Later activation materializes only the managed bundle.

The downloadable bundle is never materialized for ordinary use and is never used as a future refresh source.

## Failure and security invariants

- A refresh operation never partially promotes one output.
- Both outputs must have refresh tokens distinct from the source and from each other.
- Both outputs must match the enrolled email and workspace.
- Token contents never enter logs, URLs, events, or view models.
- Download responses remain non-cacheable attachments behind session, CSRF, and administrator reauthentication.
- Replacing the local export does not revoke copies downloaded earlier.
- Both lineages share the same upstream account and quota.
- If OpenAI removes refresh-token reuse, Windowkeeper fails closed and keeps the last good bundles.
