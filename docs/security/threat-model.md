# Threat model

Scope: multi-user DataWorks Agent (control plane + per-user OpenCode workers + PyODPS sidecar + browser app).

## Assets

- DataWorks / MaxCompute credentials
- LLM provider credentials
- Browser session tokens (`dwa_session`)
- Per-user files, Skills, knowledge chunks, audit logs
- Write tickets (single-use)
- Package artifacts and backups

## Threats and controls

### Browser session theft

- **Threat:** Stolen cookie → impersonation.
- **Controls:** HttpOnly + SameSite=Lax (+ Secure in non-dev); idle/absolute session expiry; logout invalidation; reauthentication for backup export.

### CSRF

- **Threat:** Cross-origin POST/WebSocket using victim cookie.
- **Controls:** Origin / Sec-Fetch-Site checks (`checkOrigin`); reject mismatched Origin with 403; cookie not accepted on internal worker routes.

### Worker breakout

- **Threat:** User worker escapes to host or other users.
- **Controls:** Per-user roots; production OCI isolation; native mode limited for multi-user; private-path deny; no real cloud secrets in worker env (gateway injects).

### Path traversal / symlink / junction

- **Threat:** Read/write outside allowed roots via `..`, symlinks, Windows junctions.
- **Controls:** `PrivatePathPolicy` + OpenCode `assertNotPrivatePathEffect` before PermissionV1; resolve + realpath nearest parent; mandatory deny patterns that user config cannot weaken.

### Plugin prompt injection

- **Threat:** Malicious Skill or tool output steers agent to exfiltrate data or call write tools.
- **Controls:** Skill allow/deny tool lists; write tools default `ask`; ticket + reason required; RAG context quoted as untrusted; egress policy for knowledge inject.

### Malicious documents

- **Threat:** Upload macros/scripts for RCE or XSS.
- **Controls:** MIME/extension allowlist; size limit (50MB); parser worker isolation (no network); no macro execution; sanitize paths in citations.

### Secret / log leakage

- **Threat:** AK/SK, tokens, SQL rows in logs, audit, or acceptance artifacts.
- **Controls:** Redacted credentials; audit stores hashes/metadata not secrets; acceptance artifacts mask ids; package scripts never bundle secrets; lint CI for accidental fixtures.

### MCP endpoint abuse

- **Threat:** Untrusted MCP server SSRF or tool storm.
- **Controls:** Allowlisted MCP endpoints; timeouts; dry-run fallback; audit MCP calls; no cookie on internal MCP bridges.

### Write-ticket replay

- **Threat:** Reuse captured ticket for second write.
- **Controls:** Single-use consume; args hash bind; TTL; connection write_enabled gate; deny when disabled.

### Staging credential misuse

- **Threat:** Staging AK used against production projects or shared widely.
- **Controls:** Dedicated staging secrets in CI Environment; least privilege; write tests only with `DWA_STAGING_WRITE_TEST=1` on fixtures; hard-fail acceptance without secrets (no skip-as-pass).

### Sidecar protocol abuse

- **Threat:** Malformed PyODPS protocol → host command execution or data exfil.
- **Controls:** Structured protocol; SQL policy bans DML/DDL tokens; dry-run mode; process supervisor restart; no shell interpolation of SQL.

### Backup exposure

- **Threat:** Archive or `secrets.dat` disclosure.
- **Controls:** `secrets.dat` useless without keyring; export requires reauthentication + passphrase-encrypted archive; exclude secrets from dist artifacts (see `docs/operations/backup-restore.md`).

## Residual risks

- Native multi-user without OCI is weaker isolation.
- Full semantic embedding quality depends on packaged model fetch (may be PENDING in dry-run).
- Staging write drills require human-operated fixtures and must restore state.
- Placeholder package binaries in dry-run are not production installers.

## Review cadence

Revisit this model on each upstream-sync and before every minor release.
