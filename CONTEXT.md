# Windowkeeper glossary

## Account

A locally named representation of one authenticated ChatGPT identity and its usage history, scheduling, and activation state.

## Managed credential bundle

The credential lineage Windowkeeper uses for an account's isolated Codex operations and keeps current through normal Codex refresh behavior.

## Downloadable credential bundle

The latest `auth.json` branch derived alongside the managed branch from one source refresh token. Windowkeeper replaces it locally after each successful refresh, holds it encrypted for administrator download, and never uses it for operations.

## Enrollment

The creation of a new account from one ChatGPT approval, followed immediately by two Codex-managed refresh exchanges that create the managed and downloadable bundles.

## Reauthentication

Replacement of both credential bundles from one new ChatGPT approval and the same two-way refresh process.
