-- 0001_auth.sql
-- SHA-256: b2896cfa8e81b625a3fbd807d20afadeb6f81b4bf461755c9b3577f888b61a95

CREATE TABLE IF NOT EXISTS dwa_user (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  disabled INTEGER NOT NULL DEFAULT 0,
  time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dwa_browser_session (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  time_expires INTEGER NOT NULL,
  time_created INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES dwa_user(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_browser_session_user_id ON dwa_browser_session(user_id);
CREATE INDEX IF NOT EXISTS idx_browser_session_time_expires ON dwa_browser_session(time_expires);
