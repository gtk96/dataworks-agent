#!/usr/bin/env bun
/**
 * Package DataWorks Agent distribution artifacts.
 *
 * Produces:
 *   dataworks-agent-<version>-windows-x64.zip
 *   dataworks-agent-<version>-linux-x64.tar.gz
 *   SHA256SUMS
 *   sbom.spdx.json
 *   THIRD_PARTY_LICENSES.txt
 *
 * When full native builds are unavailable, writes honest dry-run placeholders
 * under artifacts/dist (or ARTIFACTS_DIR) and documents remaining external gates.
 */
import { createHash } from "crypto"
import { mkdirSync, writeFileSync, readFileSync, existsSync, cpSync, readdirSync } from "fs"
import { join, resolve } from "path"

const ROOT = resolve(import.meta.dir, "..")
const version =
  process.env.DATAWORKS_AGENT_VERSION ??
  process.env.VERSION ??
  readVersionFromPackage() ??
  "0.1.0"

const outDir = resolve(process.env.ARTIFACTS_DIR ?? join(ROOT, "artifacts", "dist"))
const dryRun = process.env.DATAWORKS_AGENT_DRY_RUN !== "0" || process.argv.includes("--dry-run")

function readVersionFromPackage(): string | undefined {
  try {
    const raw = readFileSync(join(ROOT, "packages/dataworks-core/package.json"), "utf8")
    const match = /"version"\s*:\s*"([^"]+)"/.exec(raw)
    return match?.[1]
  } catch {
    return undefined
  }
}

function hashFile(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex")
}

function writePlaceholder(path: string, title: string) {
  writeFileSync(
    path,
    [
      title,
      `version=${version}`,
      `generatedAt=${new Date().toISOString()}`,
      dryRun ? "mode=dry-run-placeholder" : "mode=release-skeleton",
      "Full native packaging builds OpenCode worker + control plane + app + uv-locked pyodps sidecar.",
      "Do not bundle credentials, secrets.dat, or local app-data.",
      "",
    ].join("\n"),
  )
}

function writeLicenses(path: string) {
  const rootLicense = existsSync(join(ROOT, "LICENSE"))
    ? readFileSync(join(ROOT, "LICENSE"), "utf8").slice(0, 4000)
    : "MIT (see repository LICENSE)"
  writeFileSync(
    path,
    [
      "THIRD PARTY LICENSES — DataWorks Agent",
      "",
      "## OpenCode (upstream)",
      "Repository: https://github.com/anomalyco/opencode",
      "License: MIT",
      "",
      "## DataWorks Agent local packages",
      "License: MIT",
      "",
      "## Root LICENSE excerpt",
      rootLicense,
      "",
      "Package maintainers must preserve upstream notices when redistributing.",
      "",
    ].join("\n"),
  )
}

function writeSbom(path: string) {
  const packages: Array<Record<string, string>> = [
    {
      name: "dataworks-agent",
      SPDXID: "SPDXRef-Package-dataworks-agent",
      versionInfo: version,
      downloadLocation: "NOASSERTION",
      licenseConcluded: "MIT",
    },
    {
      name: "opencode",
      SPDXID: "SPDXRef-Package-opencode",
      versionInfo: "upstream-baseline",
      downloadLocation: "git+https://github.com/anomalyco/opencode",
      licenseConcluded: "MIT",
    },
  ]
  // Enumerate workspace package names when present
  const packagesDir = join(ROOT, "packages")
  if (existsSync(packagesDir)) {
    for (const name of readdirSync(packagesDir)) {
      if (!name.startsWith("dataworks-")) continue
      packages.push({
        name,
        SPDXID: `SPDXRef-Package-${name}`,
        versionInfo: version,
        downloadLocation: "NOASSERTION",
        licenseConcluded: "MIT",
      })
    }
  }
  writeFileSync(
    path,
    JSON.stringify(
      {
        spdxVersion: "SPDX-2.3",
        dataLicense: "CC0-1.0",
        SPDXID: "SPDXRef-DOCUMENT",
        name: `dataworks-agent-${version}`,
        documentNamespace: `https://dataworks-agent.local/spdx/${version}`,
        creationInfo: {
          created: new Date().toISOString(),
          creators: ["Tool: scripts/package-dataworks-agent.ts"],
        },
        packages,
      },
      null,
      2,
    ) + "\n",
  )
}

function main() {
  mkdirSync(outDir, { recursive: true })

  // Optionally stage a bundle skeleton (no secrets)
  const stage = join(outDir, "stage")
  mkdirSync(stage, { recursive: true })
  writeFileSync(
    join(stage, "start.sh"),
    "#!/usr/bin/env bash\nset -euo pipefail\nbun packages/dataworks-control/src/cli/start.ts \"$@\"\n",
  )
  writeFileSync(
    join(stage, "start.ps1"),
    "bun packages/dataworks-control/src/cli/start.ts @args\n",
  )
  writeFileSync(
    join(stage, "README.txt"),
    [
      "DataWorks Agent package skeleton",
      `version=${version}`,
      "",
      "1. Install Bun 1.3.14+",
      "2. bun install --frozen-lockfile",
      "3. bun run create-admin",
      "4. bun run start",
      "5. Open the public origin and complete dry-run / staging acceptance",
      "",
      "Sidecar: use uv lock under sidecars/pyodps; do not vendor cloud credentials.",
      "",
    ].join("\n"),
  )

  if (existsSync(join(ROOT, "sidecars/pyodps"))) {
    // Copy only non-secret sidecar metadata (pyproject / lock if present)
    const py = join(ROOT, "sidecars/pyodps")
    for (const f of ["pyproject.toml", "uv.lock", "README.md"]) {
      const src = join(py, f)
      if (existsSync(src)) {
        mkdirSync(join(stage, "sidecars", "pyodps"), { recursive: true })
        cpSync(src, join(stage, "sidecars", "pyodps", f))
      }
    }
  }

  const winName = `dataworks-agent-${version}-windows-x64.zip`
  const linuxName = `dataworks-agent-${version}-linux-x64.tar.gz`
  writePlaceholder(join(outDir, winName), "DataWorks Agent windows-x64 package payload")
  writePlaceholder(join(outDir, linuxName), "DataWorks Agent linux-x64 package payload")
  writeLicenses(join(outDir, "THIRD_PARTY_LICENSES.txt"))
  writeSbom(join(outDir, "sbom.spdx.json"))

  const files = [winName, linuxName, "sbom.spdx.json", "THIRD_PARTY_LICENSES.txt"]
  const sums = files.map((f) => `${hashFile(join(outDir, f))}  ${f}`)
  writeFileSync(join(outDir, "SHA256SUMS"), sums.join("\n") + "\n")

  writeFileSync(
    join(outDir, "README.md"),
    [
      `# dataworks-agent ${version} distribution`,
      "",
      dryRun
        ? "**Dry-run / skeleton mode.** Full binary packaging (Windows zip + Linux tar.gz with native worker) remains an external gate (clean Sandbox/container verification)."
        : "Release skeleton generated. Attach CI-built binaries when the release workflow completes.",
      "",
      "## Artifacts",
      "",
      ...files.map((f) => `- ${f}`),
      "- SHA256SUMS",
      "",
      "## Never include",
      "",
      "- secrets.dat / OS keyring material",
      "- staging AK/SK",
      "- local user roots / LanceDB user data",
      "",
      "## Verify",
      "",
      "```bash",
      "sha256sum -c SHA256SUMS",
      "bun run acceptance:dry-run",
      "```",
      "",
    ].join("\n"),
  )

  console.log(`[package] wrote artifacts to ${outDir}`)
  for (const line of sums) console.log(line)
}

main()
