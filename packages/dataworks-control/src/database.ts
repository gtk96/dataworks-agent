import { createHash } from "crypto"
import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { Database as SqliteDatabase } from "bun:sqlite"
import { drizzle, SQLiteBunDatabase } from "drizzle-orm/bun-sqlite"
import { eq, lt, and, desc } from "drizzle-orm"
import { UserTable, BrowserSessionTable, RateLimitTable, DataConnectionTable } from "./schema"
import type { UserID } from "@dataworks-agent/core"

export interface AppConfig {
  dbPath: string
  migrationsDir: string
}

// Keep run/get/all/transaction interface for backward compat with existing callers
export interface Database {
  readonly _: SQLiteBunDatabase
  run(sql: string, params?: (string | number | null)[]): void
  get<T>(sql: string, params?: (string | number | null)[]): T | undefined
  all<T>(sql: string, params?: (string | number | null)[]): T[]
  transaction(fn: () => void): void
  close(): void
}

export async function makeDatabase(config: AppConfig): Promise<Database> {
  const db = new SqliteDatabase(config.dbPath, { create: true })
  db.run("PRAGMA journal_mode = DELETE")
  db.run("PRAGMA synchronous = NORMAL")
  db.run("PRAGMA busy_timeout = 5000")
  db.run("PRAGMA foreign_keys = ON")

  await runMigrations(db, config.migrationsDir)

  const drizzleDb = drizzle({ client: db })
  return wrapDatabase(db, drizzleDb)
}

function wrapDatabase(db: SqliteDatabase, drizzleDb: SQLiteBunDatabase): Database {
  return {
    get _() {
      return drizzleDb
    },

    run(sql: string, params?: (string | number | null)[]) {
      const statement = db.prepare(sql)
      try {
        if (params) {
          statement.run(...params)
        } else {
          statement.run()
        }
      } finally {
        statement.finalize()
      }
    },

    get<T>(sql: string, params?: (string | number | null)[]): T | undefined {
      const statement = db.prepare(sql)
      try {
        if (params) {
          return statement.get(...params) as T | undefined
        }
        return statement.get() as T | undefined
      } finally {
        statement.finalize()
      }
    },

    all<T>(sql: string, params?: (string | number | null)[]): T[] {
      const statement = db.prepare(sql)
      try {
        if (params) {
          return statement.all(...params) as T[]
        }
        return statement.all() as T[]
      } finally {
        statement.finalize()
      }
    },

    transaction(fn: () => void) {
      db.exec("BEGIN TRANSACTION")
      try {
        fn()
        db.exec("COMMIT")
      } catch (error) {
        db.exec("ROLLBACK")
        throw error
      }
    },

    close() {
      Bun.gc(true)
      db.close(true)
    },
  }
}

async function runMigrations(db: SqliteDatabase, migrationsDir: string) {
  db.prepare(`
    CREATE TABLE IF NOT EXISTS dwa_migration (
      id TEXT PRIMARY KEY,
      sha256 TEXT NOT NULL,
      time_completed INTEGER NOT NULL
    )
  `).run()

  const migrationFiles = readdirSync(migrationsDir)
    .filter((f) => f.endsWith(".sql"))
    .sort()

  for (const file of migrationFiles) {
    const id = file.replace(".sql", "")
    const content = readFileSync(join(migrationsDir, file), "utf-8")
    const sha256 = createHash("sha256").update(content).digest("hex")

    const existing = db.prepare("SELECT sha256 FROM dwa_migration WHERE id = ?").get(id) as
      | { sha256: string }
      | undefined

    if (existing) {
      if (existing.sha256 !== sha256) {
        throw new Error(
          `Migration ${id} has been modified after being applied. Original: ${existing.sha256}, Current: ${sha256}`,
        )
      }
      continue
    }

    db.exec("BEGIN TRANSACTION")
    try {
      const strippedContent = content
        .split("\n")
        .filter((line) => !line.trim().startsWith("--"))
        .join("\n")

      const statements = strippedContent.split(";").map((s) => s.trim()).filter((s) => s.length > 0)

      for (const stmtText of statements) {
        db.prepare(stmtText).run()
      }

      db.prepare("INSERT INTO dwa_migration (id, sha256, time_completed) VALUES (?, ?, ?)").run(
        id,
        sha256,
        Date.now(),
      )
      db.exec("COMMIT")
    } catch (error) {
      db.exec("ROLLBACK")
      throw error
    }
  }
}

// Typed query helpers for modules - expose Drizzle queries
export function queryUserById(db: Database, id: UserID) {
  return db._.select().from(UserTable).where(eq(UserTable.id, id)).get()
}

export function queryUserByEmail(db: Database, email: string) {
  return db._.select().from(UserTable).where(eq(UserTable.email, email)).get()
}

export function querySessionByTokenHash(db: Database, tokenHash: string) {
  return db._.select().from(BrowserSessionTable).where(eq(BrowserSessionTable.token_hash, tokenHash)).get()
}

export function insertSession(
  db: Database,
  data: { token_hash: string; user_id: UserID; time_expires: number; time_created: number },
) {
  return db._.insert(BrowserSessionTable).values(data).run()
}

export function deleteSessionByTokenHash(db: Database, tokenHash: string) {
  return db._.delete(BrowserSessionTable).where(eq(BrowserSessionTable.token_hash, tokenHash)).run()
}

export function deleteExpiredSessions(db: Database, now: number) {
  return db._.delete(BrowserSessionTable).where(lt(BrowserSessionTable.time_expires, now)).run()
}

export function queryRateLimit(db: Database, ipAddress: string, email: string) {
  return db._
    .select()
    .from(RateLimitTable)
    .where(and(eq(RateLimitTable.ip_address, ipAddress), eq(RateLimitTable.email, email)))
    .get()
}

export function upsertRateLimit(
  db: Database,
  data: { ip_address: string; email: string; failure_count: number; first_failure: number },
) {
  return db._
    .insert(RateLimitTable)
    .values(data)
    .onConflictDoUpdate({
      target: [RateLimitTable.ip_address, RateLimitTable.email],
      set: {
        failure_count: data.failure_count,
        first_failure: data.first_failure,
      },
    })
    .run()
}

export function deleteRateLimit(db: Database, ipAddress: string, email: string) {
  return db._
    .delete(RateLimitTable)
    .where(and(eq(RateLimitTable.ip_address, ipAddress), eq(RateLimitTable.email, email)))
    .run()
}

export function listDataConnectionsByUser(db: Database, userId: UserID) {
  return db._
    .select()
    .from(DataConnectionTable)
    .where(eq(DataConnectionTable.user_id, userId))
    .orderBy(desc(DataConnectionTable.time_created))
    .all()
}

export function queryDataConnection(db: Database, id: string, userId: UserID) {
  return db._
    .select()
    .from(DataConnectionTable)
    .where(and(eq(DataConnectionTable.id, id), eq(DataConnectionTable.user_id, userId)))
    .get()
}

export function insertDataConnection(
  db: Database,
  data: {
    id: string
    user_id: UserID
    name: string
    region: string
    access_key_id: string
    access_key_display: string
    secret_ref: string
    write_enabled: boolean
    time_created: number
    time_updated: number
  },
) {
  return db._.insert(DataConnectionTable).values(data).run()
}

export function deleteDataConnection(db: Database, id: string, userId: UserID) {
  return db._
    .delete(DataConnectionTable)
    .where(and(eq(DataConnectionTable.id, id), eq(DataConnectionTable.user_id, userId)))
    .run()
}
