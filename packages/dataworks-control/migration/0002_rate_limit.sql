-- 0002_rate_limit.sql
-- SHA-256: 4d8e2f1a3b5c7d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3

CREATE TABLE IF NOT EXISTS dwa_rate_limit (
  ip_address TEXT NOT NULL,
  email TEXT NOT NULL,
  failure_count INTEGER NOT NULL DEFAULT 0,
  first_failure INTEGER NOT NULL,
  PRIMARY KEY (ip_address, email)
);
