# Backup and restore

## What is backed up

| Path / resource | Contents | Restorable alone? |
|---|---|---|
| Control-plane SQLite (`control.sqlite`) | users, sessions metadata, connections metadata, audit | Yes, with schema migrations |
| `secrets.dat` | AES-256-GCM ciphertext for DataWorks/LLM credentials | **No** — needs OS keyring master key |
| OS keyring entry | Master key for `secrets.dat` | Required with `secrets.dat` |
| Per-user worker roots | OpenCode session/local state | Yes, but isolate by user id |
| Knowledge indexes (LanceDB / memory) | Embeddings + chunks | Yes; rebuild from document store if corrupt |
| App config | Non-secret settings | Yes |

## Critical rule: secrets.dat without keyring

**`secrets.dat` without the OS keyring entry is not independently restorable.**

The master key is sealed in the platform keyring (Windows DPAPI / macOS Keychain / Linux secret service). Copying only `secrets.dat` to another machine yields ciphertext that cannot be decrypted.

## Export flow (operator)

1. Authenticate as an admin (reauthentication required — existing session cookie alone is insufficient for export).
2. Confirm export intent and provide a **passphrase** (≥ 16 characters recommended).
3. Control plane derives an export key from the passphrase (memory-hard KDF), re-wraps credential material, and writes a single encrypted archive:
   - `export-<timestamp>.dwaarchive`
   - Contains: schema version, user/connection metadata, re-encrypted secrets blob, optional knowledge file list (not raw secrets).
4. Store the archive offline. Do **not** log the passphrase or archive bytes.

## Restore flow

1. Install DataWorks Agent on the target host; create a fresh admin via `bun run create-admin`.
2. Import archive: supply the same passphrase; control plane unwraps credentials into a **new** local keyring + `secrets.dat`.
3. Run `bun run acceptance:dry-run`, then staging smoke with least-privilege staging credentials (not production).
4. Rotate any credentials that may have been exposed during transport.

## Backup exposure threats

- Unencrypted disk images of app-data roots
- Archive copies without access control
- Including `secrets.dat` in git or CI artifacts
- Sharing keyring backups with archives over the same channel

Mitigations: encrypt archives, separate channels for passphrase, exclude secrets from package artifacts and CI logs, mandatory reauthentication on export.
