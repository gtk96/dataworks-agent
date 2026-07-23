-- 0005_audit_tickets.sql
-- The brief listed 0004, but the existing migration chain already uses 0004 for LLM connections.
-- Audit rows intentionally contain hashes and metadata only, never raw arguments or results.

CREATE TABLE IF NOT EXISTS dwa_audit (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  session_id TEXT,
  tool TEXT NOT NULL,
  permission TEXT NOT NULL CHECK (permission IN ('read', 'write')),
  args_hash TEXT NOT NULL,
  reason TEXT,
  outcome TEXT NOT NULL CHECK (outcome IN ('success', 'error', 'denied')),
  error_code TEXT,
  duration_ms INTEGER NOT NULL,
  time_created INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audit_user_time ON dwa_audit(user_id, time_created DESC);
CREATE INDEX IF NOT EXISTS idx_audit_connection_time ON dwa_audit(connection_id, time_created DESC);

CREATE TABLE IF NOT EXISTS dwa_write_ticket (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  session_id TEXT,
  tool TEXT NOT NULL,
  args_hash TEXT NOT NULL,
  reason TEXT NOT NULL,
  time_expires INTEGER NOT NULL,
  time_consumed INTEGER,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE,
  FOREIGN KEY (connection_id) REFERENCES dwa_data_connection(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_write_ticket_user ON dwa_write_ticket(user_id);
CREATE INDEX IF NOT EXISTS idx_write_ticket_expires ON dwa_write_ticket(time_expires);
