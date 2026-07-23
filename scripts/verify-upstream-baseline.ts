import baseline from "../upstream-baseline.json"

const result = Bun.spawnSync(["git", "merge-base", "--is-ancestor", baseline.commit, "HEAD"])
if (result.exitCode !== 0) {
  console.error(`Pinned upstream commit ${baseline.commit} is not an ancestor of HEAD`)
  process.exit(1)
}
console.log(`${baseline.repository}@${baseline.commit}`)
