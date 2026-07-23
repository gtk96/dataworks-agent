import { join } from "path"
import { realpathSync, existsSync } from "fs"

export interface UserPrivateRoots {
  home: string
  data: string
  config: string
  cache: string
}

export function userPrivateRoots(appDataRoot: string, userId: string): UserPrivateRoots {
  const safe = /^[a-zA-Z0-9_-]{1,64}$/
  if (!safe.test(userId)) {
    throw new Error("invalid_user_id")
  }
  const parent = realpathSync(appDataRoot)
  const base = join(parent, "users", userId)
  return {
    home: join(base, "home"),
    data: join(base, "data"),
    config: join(base, "config"),
    cache: join(base, "cache"),
  }
}

export function ensurePaths(roots: UserPrivateRoots): void {
  const { mkdirSync } = require("fs") as typeof import("fs")
  for (const p of [roots.home, roots.data, roots.config, roots.cache]) {
    const parent = join(p, "..")
    if (!existsSync(parent)) mkdirSync(parent, { recursive: true })
    if (!existsSync(p)) mkdirSync(p, { recursive: true })
  }
}
