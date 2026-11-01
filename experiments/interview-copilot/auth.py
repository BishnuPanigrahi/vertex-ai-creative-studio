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
"""Email/password accounts, cookie sessions and per-plan usage limits."""

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, HTTPException, Response

import db

COOKIE_NAME = "poised_session"
SESSION_DAYS = 30
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

# Daily limits per plan; None means unlimited.
PLAN_LIMITS: dict[str, dict[str, int | None]] = {
    "free": {"question": 5, "coding": 3, "assist": 10, "match": 1},
    "pro": {"question": None, "coding": None, "assist": None, "match": None},
}


def hash_password(password: str) -> str:
    """Hash a password with scrypt and a random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored scrypt hash."""
    salt_hex, digest_hex = stored.split("$", 1)
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt_hex),
        n=2**14,
        r=8,
        p=1,
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(response: Response, user_id: int) -> None:
    """Create a login session and set its cookie."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=SESSION_DAYS)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO login_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (_token_hash(token), user_id, expires.isoformat()),
        )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )


def end_session(response: Response, token: str | None) -> None:
    """Delete the login session and clear its cookie."""
    if token:
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM login_sessions WHERE token_hash = ?",
                (_token_hash(token),),
            )
    response.delete_cookie(COOKIE_NAME)


def current_user(poised_session: str | None = Cookie(None)) -> sqlite3.Row:
    """FastAPI dependency returning the signed-in user, or raising 401."""
    if not poised_session:
        raise HTTPException(status_code=401, detail="Please sign in.")
    with db.connect() as conn:
        row = conn.execute(
            """SELECT users.* FROM login_sessions
               JOIN users ON users.id = login_sessions.user_id
               WHERE token_hash = ? AND expires_at > ?""",
            (_token_hash(poised_session), datetime.now(UTC).isoformat()),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=401,
            detail="Your session expired. Please sign in.",
        )
    return row


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def usage_today(user_id: int) -> dict[str, int]:
    """Return today's usage counts by kind."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT kind, count FROM usage WHERE user_id = ? AND day = ?",
            (user_id, _today()),
        ).fetchall()
    return {r["kind"]: r["count"] for r in rows}


def consume(user: sqlite3.Row, kind: str) -> None:
    """Count one use of `kind`, raising 402 if the plan's daily limit is reached."""
    limit = PLAN_LIMITS.get(user["plan"], PLAN_LIMITS["free"]).get(kind)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT count FROM usage WHERE user_id = ? AND day = ? AND kind = ?",
            (user["id"], _today(), kind),
        ).fetchone()
        used = row["count"] if row else 0
        if limit is not None and used >= limit:
            raise HTTPException(
                status_code=402,
                detail=f"You've used today's free {kind} limit ({limit}). Upgrade to Pro for unlimited practice.",
            )
        conn.execute(
            """INSERT INTO usage (user_id, day, kind, count) VALUES (?, ?, ?, 1)
               ON CONFLICT(user_id, day, kind) DO UPDATE SET count = count + 1""",
            (user["id"], _today(), kind),
        )
