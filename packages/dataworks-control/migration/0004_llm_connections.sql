-- 0004_llm_connections.sql
-- LLM connection metadata + secret_ref for safe credential proxying.
-- The brief listed 0003 but Task 3 already used 0003 for data_connections.

CREATE TABLE IF NOT EXISTS dwa_llm_connection (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  name TEXT NOT NULL,
  upstream_origin TEXT NOT NULL,
  auth_strategy TEXT NOT NULL,
  secret_ref TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  allowed_models TEXT NOT NULL DEFAULT '[]',
  data_classification_allowlist TEXT NOT NULL DEFAULT 'prompt_only',
  time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_llm_connection_user_name ON dwa_llm_connection(user_id, name);
CREATE INDEX IF NOT EXISTS idx_llm_connection_user_id ON dwa_llm_connection(user_id);
CREATE INDEX IF NOT EXISTS idx_llm_connection_provider_id ON dwa_llm_connection(provider_id);
