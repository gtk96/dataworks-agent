# Upstream Policy

- Origin: https://github.com/gtk96/opencode.git
- Upstream: https://github.com/anomalyco/opencode.git
- Tracked branch: dev
- Initial baseline: cd46f22d513d60b7a9bdca1111d25c50d2398355
- Sync branch: upstream-sync
- Sync cadence: monthly and before every minor release
- Merge gate: package typechecks, OpenCode HttpApi exercise, DataWorks dry-run integration, Playwright critical path
- Core conflict policy: prefer upstream behavior; keep DataWorks changes in new packages/API groups/pages; document every unavoidable core patch in this file.

## Baseline notices

Pinned commit `cd46f22d513d60b7a9bdca1111d25c50d2398355` has no root `NOTICE` file. DataWorks Agent preserves the actual upstream root `LICENSE` and package-level license files without inventing an upstream notice.

## Core patches (DataWorks)

### Task 11 — Private-path mandatory deny + write-tool permission defaults

These OpenCode core patches protect native single-user mode and prevent accidental mounts from exposing control-plane private paths. OCI containment remains the production boundary.

| File | Patch |
|------|--------|
| `packages/opencode/src/tool/private-path.ts` | **New.** Single mandatory guard. Parses `DWA_PRIVATE_PATHS` (JSON array of absolute roots), `path.resolve` + nearest-existing-parent `fs.realpath` + reattach missing suffix, Windows case-folding. Returns typed `PrivatePathDeny` **before** any PermissionV1 prompt. |
| `packages/opencode/src/tool/external-directory.ts` | Call `assertNotPrivatePathEffect(full, "external_directory")` before `external_directory` ask / project-contains short-circuit. |
| `packages/opencode/src/tool/read.ts` | Call `assertNotPrivatePathEffect(filepath, "read")` after path resolve, before external-directory / read permission. |
| `packages/opencode/src/tool/edit.ts` | Call `assertNotPrivatePathEffect(filePath, "edit")` before external-directory. |
| `packages/opencode/src/tool/write.ts` | Call `assertNotPrivatePathEffect(filepath, "write")` before external-directory. |
| `packages/opencode/src/tool/apply_patch.ts` | Call `assertNotPrivatePathEffect(filePath, "apply_patch")` per hunk path before external-directory. |
| `packages/opencode/src/tool/shell.ts` | Track every shell-parser-discovered path in `scan.files`; call `assertNotPrivatePathEffect` for each `scan.dirs` / `scan.files` entry inside `ShellTool.ask` **before** external_directory / bash permission prompts. Paths inside the project are still checked (private roots may be mounted inside). |
| `packages/opencode/src/agent/agent.ts` | (1) Default `dw_write: "ask"`. (2) Build `privatePathDeny` from `DWA_PRIVATE_PATHS` with deny patterns for `read`/`edit`/`external_directory`/`private_path`, and re-assert `dw_write: "ask"`. (3) Merge `privatePathDeny` **after** user rules on every agent (build/plan/general/explore/compaction/title/summary + custom) so user config cannot turn private-path access into `always allow`. |

Shared policy source of truth for unit tests: `packages/dataworks-core/src/private-path.ts` (`PrivatePathPolicy.check` / `assert`). The OpenCode tool module duplicates the algorithm intentionally (no hard workspace dep from opencode → dataworks-core).
