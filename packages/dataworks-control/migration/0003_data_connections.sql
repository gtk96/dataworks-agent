-- 0003_data_connections.sql
-- DataConnection metadata + secret_ref; never stores AK/SK plaintext.

CREATE TABLE IF NOT EXISTS dwa_data_connection (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  region TEXT NOT NULL,
  access_key_id TEXT NOT NULL,
  access_key_display TEXT NOT NULL,
  secret_ref TEXT NOT NULL,
  write_enabled INTEGER NOT NULL DEFAULT 0,
  time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_data_connection_user_name ON dwa_data_connection(user_id, name);
CREATE INDEX IF NOT EXISTS idx_data_connection_user_id ON dwa_data_connection(user_id);
