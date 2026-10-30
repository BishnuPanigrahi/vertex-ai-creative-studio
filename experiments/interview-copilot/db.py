# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""SQLite persistence for users, login sessions, practice attempts and usage."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    role TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'mid',
    resume TEXT NOT NULL DEFAULT '',
    job_description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS login_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    score INTEGER,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS attempts_user ON attempts(user_id, created_at);
CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, kind)
);
"""


def db_path() -> str:
    """Location of the SQLite file (override with DATABASE_PATH)."""
    return os.environ.get("DATABASE_PATH", str(Path(__file__).parent / "poised.db"))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection that commits on success and always closes."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    """Create tables if they do not exist."""
    with connect() as conn:
        conn.executescript(SCHEMA)
