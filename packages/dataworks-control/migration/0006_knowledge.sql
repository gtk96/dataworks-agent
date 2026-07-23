-- 0006_knowledge.sql
-- Brief listed 0005_knowledge.sql, but the existing migration chain already uses
-- 0005 for audit_tickets. Knowledge metadata is therefore 0006.

CREATE TABLE IF NOT EXISTS dwa_knowledge_base (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  egress_policy TEXT NOT NULL DEFAULT 'local_only' CHECK (egress_policy IN ('local_only', 'approved_providers')),
  approved_providers TEXT NOT NULL DEFAULT '[]',
  embedding_provider TEXT NOT NULL DEFAULT 'local' CHECK (embedding_provider IN ('local', 'remote')),
  index_status TEXT NOT NULL DEFAULT 'missing' CHECK (index_status IN ('ready', 'degraded', 'rebuilding', 'missing')),
  time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_base_user_name ON dwa_knowledge_base(user_id, name);
CREATE INDEX IF NOT EXISTS idx_knowledge_base_user ON dwa_knowledge_base(user_id);

CREATE TABLE IF NOT EXISTS dwa_knowledge_document (
  id TEXT PRIMARY KEY,
  knowledge_base_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  byte_size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  page_count INTEGER,
  error TEXT,
  connection_id TEXT,
  storage_relpath TEXT,
  time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE,
  FOREIGN KEY (knowledge_base_id) REFERENCES dwa_knowledge_base(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_knowledge_document_kb ON dwa_knowledge_document(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_document_user ON dwa_knowledge_document(user_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_document_sha ON dwa_knowledge_document(user_id, sha256);

CREATE TABLE IF NOT EXISTS dwa_knowledge_index_job (
  id TEXT PRIMARY KEY,
  knowledge_base_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  document_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('index', 'rebuild')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
  error TEXT,
  time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE,
  FOREIGN KEY (knowledge_base_id) REFERENCES dwa_knowledge_base(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_knowledge_index_job_kb ON dwa_knowledge_index_job(knowledge_base_id, status);

CREATE TABLE IF NOT EXISTS dwa_knowledge_provider_approval (
  id TEXT PRIMARY KEY,
  knowledge_base_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  time_created INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE,
  FOREIGN KEY (knowledge_base_id) REFERENCES dwa_knowledge_base(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_knowledge_provider_approval
  ON dwa_knowledge_provider_approval(knowledge_base_id, provider_id);
