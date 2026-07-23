# Upstream sync

## Policy

See root `UPSTREAM.md` for origin, upstream remote, pinned baseline, and documented core patches.

- Upstream: `https://github.com/anomalyco/opencode.git` branch `dev`
- Sync branch: `upstream-sync`
- Cadence: monthly and before every minor release
- Prefer upstream behavior; keep DataWorks changes in `packages/dataworks-*`, sidecars, tests, and docs

## Rehearsal checklist

```bash
git switch -c upstream-sync
git fetch upstream dev
git merge --no-ff upstream/dev

bun install --frozen-lockfile
bun run verify:upstream
bun run acceptance:dry-run
```

Package typechecks (cheap matrix):

```bash
bun run --cwd packages/core typecheck
bun run --cwd packages/opencode typecheck
bun run --cwd packages/dataworks-core typecheck
bun run --cwd packages/dataworks-control typecheck
bun run --cwd packages/dataworks-plugin typecheck
bun run --cwd packages/app typecheck
```

## Conflict handling

1. Record every conflict path and resolution in the sync PR description.
2. Prefer extracting local patches into `packages/dataworks-*` or plugin hooks rather than growing core forks.
3. If a core patch remains unavoidable, update `UPSTREAM.md` **Core patches** table with file, purpose, and removal criteria.
4. Update `upstream-baseline.json` **only after** full verification + human review.

## CI

`.github/workflows/upstream-sync.yml` and `verify.yml` exercise baseline verification and dry-run integration. Release publish still requires staging Environment approval (`release.yml`).

## Do not

- Force-push rewritten upstream history into `dev` without review
- Publish release artifacts from the sync feature branch
- Drop MIT license/notice files during merge
