-- No passwords: identity comes from the reverse proxy (Authelia).
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL
);

-- Exact links: /<slug> -> target
CREATE TABLE IF NOT EXISTS links (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT NOT NULL UNIQUE,
    target     TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    visits     INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL REFERENCES users(username),
    created_at TEXT NOT NULL,
    expires_at TEXT
);

-- Pattern rules (admin only). Lowest priority number is tried first.
CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern    TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'glob' CHECK (match_type IN ('glob', 'regex')),
    target     TEXT NOT NULL,
    priority   INTEGER NOT NULL DEFAULT 100,
    enabled    INTEGER NOT NULL DEFAULT 1,
    visits     INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL REFERENCES users(username),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
