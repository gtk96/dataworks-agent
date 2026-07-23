import { index, integer, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core"
import type { UserID } from "@dataworks-agent/core"

export const UserTable = sqliteTable("dwa_user", {
  id: text().$type<UserID>().primaryKey(),
  email: text().notNull().unique(),
  password_hash: text().notNull(),
  role: text({ enum: ["admin", "user"] }).notNull(),
  disabled: integer({ mode: "boolean" }).notNull().default(false),
  time_created: integer().notNull(),
  time_updated: integer().notNull(),
})

export const BrowserSessionTable = sqliteTable("dwa_browser_session", {
  token_hash: text().primaryKey(),
  user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
  time_expires: integer().notNull(),
  time_created: integer().notNull(),
})

export const RateLimitTable = sqliteTable("dwa_rate_limit", {
  ip_address: text().notNull(),
  email: text().notNull(),
  failure_count: integer().notNull().default(0),
  first_failure: integer().notNull(),
})

export const DataConnectionTable = sqliteTable(
  "dwa_data_connection",
  {
    id: text().primaryKey(),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    name: text().notNull(),
    region: text().notNull(),
    access_key_id: text().notNull(),
    access_key_display: text().notNull(),
    secret_ref: text().notNull(),
    write_enabled: integer({ mode: "boolean" }).notNull().default(false),
    time_created: integer().notNull(),
    time_updated: integer().notNull(),
  },
  (table) => ({
    userNameUnique: uniqueIndex("uniq_data_connection_user_name").on(table.user_id, table.name),
  }),
)

export const LlmConnectionTable = sqliteTable(
  "dwa_llm_connection",
  {
    id: text().primaryKey(),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    provider_id: text().notNull(),
    name: text().notNull(),
    upstream_origin: text().notNull(),
    auth_strategy: text().notNull(),
    secret_ref: text().notNull(),
    enabled: integer({ mode: "boolean" }).notNull().default(true),
    allowed_models: text().notNull().default("[]"),
    data_classification_allowlist: text().notNull().default("prompt_only"),
    time_created: integer().notNull(),
    time_updated: integer().notNull(),
  },
  (table) => ({
    userNameUnique: uniqueIndex("uniq_llm_connection_user_name").on(table.user_id, table.name),
  }),
)

export const AuditTable = sqliteTable(
  "dwa_audit",
  {
    id: text().primaryKey(),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    connection_id: text().notNull(),
    session_id: text(),
    tool: text().notNull(),
    permission: text({ enum: ["read", "write"] }).notNull(),
    args_hash: text().notNull(),
    reason: text(),
    outcome: text({ enum: ["success", "error", "denied"] }).notNull(),
    error_code: text(),
    duration_ms: integer().notNull(),
    time_created: integer().notNull(),
  },
  (table) => ({
    userTime: index("idx_audit_user_time").on(table.user_id, table.time_created),
    connectionTime: index("idx_audit_connection_time").on(table.connection_id, table.time_created),
  }),
)

export const WriteTicketTable = sqliteTable(
  "dwa_write_ticket",
  {
    token_hash: text().primaryKey(),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    connection_id: text().notNull().references(() => DataConnectionTable.id, { onDelete: "cascade" }),
    session_id: text(),
    tool: text().notNull(),
    args_hash: text().notNull(),
    reason: text().notNull(),
    time_expires: integer().notNull(),
    time_consumed: integer(),
  },
  (table) => ({
    user: index("idx_write_ticket_user").on(table.user_id),
    expires: index("idx_write_ticket_expires").on(table.time_expires),
  }),
)

export const KnowledgeBaseTable = sqliteTable(
  "dwa_knowledge_base",
  {
    id: text().primaryKey(),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    name: text().notNull(),
    egress_policy: text({ enum: ["local_only", "approved_providers"] }).notNull().default("local_only"),
    approved_providers: text().notNull().default("[]"),
    embedding_provider: text({ enum: ["local", "remote"] }).notNull().default("local"),
    index_status: text({ enum: ["ready", "degraded", "rebuilding", "missing"] }).notNull().default("missing"),
    time_created: integer().notNull(),
    time_updated: integer().notNull(),
  },
  (table) => ({
    userNameUnique: uniqueIndex("uniq_knowledge_base_user_name").on(table.user_id, table.name),
    user: index("idx_knowledge_base_user").on(table.user_id),
  }),
)

export const KnowledgeDocumentTable = sqliteTable(
  "dwa_knowledge_document",
  {
    id: text().primaryKey(),
    knowledge_base_id: text().notNull().references(() => KnowledgeBaseTable.id, { onDelete: "cascade" }),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    filename: text().notNull(),
    mime_type: text().notNull(),
    byte_size: integer().notNull(),
    sha256: text().notNull(),
    status: text().notNull().default("pending"),
    page_count: integer(),
    error: text(),
    connection_id: text(),
    storage_relpath: text(),
    time_created: integer().notNull(),
    time_updated: integer().notNull(),
  },
  (table) => ({
    kb: index("idx_knowledge_document_kb").on(table.knowledge_base_id),
    user: index("idx_knowledge_document_user").on(table.user_id),
  }),
)

export const KnowledgeIndexJobTable = sqliteTable(
  "dwa_knowledge_index_job",
  {
    id: text().primaryKey(),
    knowledge_base_id: text().notNull().references(() => KnowledgeBaseTable.id, { onDelete: "cascade" }),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    document_id: text(),
    kind: text({ enum: ["index", "rebuild"] }).notNull(),
    status: text({ enum: ["queued", "running", "done", "failed"] }).notNull().default("queued"),
    error: text(),
    time_created: integer().notNull(),
    time_updated: integer().notNull(),
  },
  (table) => ({
    kbStatus: index("idx_knowledge_index_job_kb").on(table.knowledge_base_id, table.status),
  }),
)

export const KnowledgeProviderApprovalTable = sqliteTable(
  "dwa_knowledge_provider_approval",
  {
    id: text().primaryKey(),
    knowledge_base_id: text().notNull().references(() => KnowledgeBaseTable.id, { onDelete: "cascade" }),
    user_id: text().$type<UserID>().notNull().references(() => UserTable.id, { onDelete: "cascade" }),
    provider_id: text().notNull(),
    time_created: integer().notNull(),
  },
  (table) => ({
    uniqueApproval: uniqueIndex("uniq_knowledge_provider_approval").on(table.knowledge_base_id, table.provider_id),
  }),
)
