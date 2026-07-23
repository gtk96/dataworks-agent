#!/usr/bin/env bun
import { join } from "path"
import { makeDatabase } from "../database"
import { createUser } from "../auth/session"

async function main() {
  const dbPath = process.env.DWA_CONTROL_DB ?? join(process.env.APPDATA ?? ".", "dataworks-agent", "control.sqlite")

  let password: string
  const bootstrapPassword = process.env.DWA_BOOTSTRAP_PASSWORD

  if (bootstrapPassword) {
    password = bootstrapPassword
  } else {
    process.stdout.write("Enter password for admin user: ")
    password = await new Promise<string>((resolve) => {
      process.stdin.once("data", (chunk) => resolve(chunk.toString().trim()))
    })
  }

  if (!password) {
    console.error("Password cannot be empty")
    process.exit(1)
  }

  const migrationsDir = join(import.meta.dir, "..", "..", "migration")
  const db = await makeDatabase({ dbPath, migrationsDir })

  try {
    await createUser({ email: "admin", password, role: "admin" }, db)
    console.log("Admin user created successfully")
  } catch (error: unknown) {
    const err = error as { message?: string }
    if (err.message?.includes("UNIQUE")) {
      console.error("Admin user already exists")
      process.exit(1)
    }
    throw error
  }
}

main()
