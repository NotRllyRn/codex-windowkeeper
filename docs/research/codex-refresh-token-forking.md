# Codex refresh-token forking research

## Finding

Codex's ChatGPT OAuth refresh token is intentionally reusable for a short server-side grace period. OpenAI engineer Eric Traut states that a refresh token may be used multiple times for roughly one hour and that each accepted reuse returns a valid access-token and refresh-token pair. The grace period exists for network and multi-process tolerance.

Source: [OpenAI Codex issue #10332 comment](https://github.com/openai/codex/issues/10332#issuecomment-3831635259).

This behavior permits two sequential refresh exchanges from one source token:

1. Refresh the source into Windowkeeper's next managed token pair.
2. Refresh the same source again into the downloadable token pair.

The exchanges must happen immediately together. The duration is an implementation detail described as “on the order of an hour,” not a durable API guarantee.

## Pinned Codex mechanism

Windowkeeper pins Codex `0.145.0`. Its app-server `account/read` handler accepts `refreshToken: true`, calls `AuthManager.refresh_token()`, and persists a successful response into that runtime's `auth.json`.

Sources:

- [`account_processor.rs` at `rust-v0.145.0`](https://github.com/openai/codex/blob/rust-v0.145.0/codex-rs/app-server/src/request_processors/account_processor.rs#L905-L999)
- [`manager.rs` at `rust-v0.145.0`](https://github.com/openai/codex/blob/rust-v0.145.0/codex-rs/login/src/auth/manager.rs#L1332-L1457)

The refresh request is sent to `https://auth.openai.com/oauth/token` with Codex's OAuth client ID, `grant_type=refresh_token`, and the stored refresh token. The response may contain ID, access, and refresh tokens; Codex persists them before the app-server request returns.

## Safe implementation boundary

Windowkeeper should not implement OpenAI's private token HTTP exchange independently. It should use the pinned Codex app-server twice, each time materializing the same encrypted source bundle into a fresh isolated home and requesting `account/read` with `refreshToken: true`.

After each exchange Windowkeeper must verify:

- the resulting `auth.json` contains a different refresh token from the source;
- both outputs resolve to the same email and workspace;
- neither durable bundle is replaced unless both exchanges succeed.

The old downloadable bundle is only deleted locally. Windowkeeper cannot promise that an already downloaded token is revoked remotely.

## Failure semantics

The app-server's account response does not directly report transient refresh failure. Windowkeeper must therefore compare the source and resulting refresh-token values. If either exchange did not rotate, the operation fails closed and retains the previous managed and downloadable bundles.

This design intentionally depends on OpenAI's documented-in-source grace behavior. If the server removes that behavior, refresh operations will fail safely rather than destroy working credentials.
