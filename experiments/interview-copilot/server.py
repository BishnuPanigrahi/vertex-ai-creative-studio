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
"""Poised: an AI interview practice coach backed by Gemini on Vertex AI."""

import io
import json
import logging
import re
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader

import ai
import auth
import billing
import db

STATIC_DIR = Path(__file__).parent / "static"
MIN_PASSWORD_LENGTH = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create database tables on startup."""
    db.init()
    yield


app = FastAPI(title="Poised", lifespan=lifespan)
User = Annotated[sqlite3.Row, Depends(auth.current_user)]


def save_attempt(  # noqa: PLR0913, PLR0917
    user: sqlite3.Row,
    kind: str,
    role: str,
    question: str,
    answer: str,
    result: dict,
) -> int:
    """Store a practice attempt in the user's history."""
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO attempts (user_id, kind, role, question, answer, score, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user["id"],
                kind,
                role,
                question,
                answer,
                result.get("score", result.get("match_score")),
                json.dumps(result),
            ),
        )
        return cur.lastrowid


# ---------- Accounts ----------


class Credentials(BaseModel):
    """Email and password for sign-up or sign-in."""

    email: str
    password: str


class Profile(BaseModel):
    """Saved defaults so users don't need to re-paste their resume."""

    role: str = ""
    level: str = "mid"
    resume: str = ""
    job_description: str = ""


@app.post("/api/auth/signup")
def signup(creds: Credentials, response: Response) -> dict:
    """Create an account and sign in."""
    email = creds.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(creds.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters.",
        )
    try:
        with db.connect() as conn:
            user_id = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, auth.hash_password(creds.password)),
            ).lastrowid
    except sqlite3.IntegrityError as e:
        raise HTTPException(
            status_code=409,
            detail="An account with that email already exists.",
        ) from e
    auth.start_session(response, user_id)
    return {"ok": True}


@app.post("/api/auth/login")
def login(creds: Credentials, response: Response) -> dict:
    """Sign in with email and password."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?",
            (creds.email.strip().lower(),),
        ).fetchone()
    if row is None or not auth.verify_password(creds.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    auth.start_session(response, row["id"])
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response, poised_session: str | None = Cookie(None)) -> dict:
    """Sign out."""
    auth.end_session(response, poised_session)
    return {"ok": True}


@app.delete("/api/account")
def delete_account(user: User, response: Response) -> dict:
    """Permanently delete the account and all its data."""
    with db.connect() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(user: User) -> dict:
    """Account details, plan limits and today's usage."""
    return {
        "email": user["email"],
        "plan": user["plan"],
        "limits": auth.PLAN_LIMITS.get(user["plan"], auth.PLAN_LIMITS["free"]),
        "usage": auth.usage_today(user["id"]),
        "billing_enabled": billing.enabled(),
        "dev_upgrade": billing.ALLOW_DEV_UPGRADE,
        "has_subscription": bool(user["stripe_customer_id"]),
        "profile": {k: user[k] for k in ("role", "level", "resume", "job_description")},
    }


@app.put("/api/profile")
def save_profile(profile: Profile, user: User) -> dict:
    """Save the user's default role, resume and job description."""
    with db.connect() as conn:
        conn.execute(
            "UPDATE users SET role = ?, level = ?, resume = ?, job_description = ? WHERE id = ?",
            (
                profile.role,
                profile.level,
                profile.resume,
                profile.job_description,
                user["id"],
            ),
        )
    return {"ok": True}


# ---------- Billing ----------


@app.post("/api/billing/checkout")
def checkout(user: User) -> dict:
    """Start a Stripe Checkout session for Pro."""
    return {
        "url": billing.checkout_url(
            user["id"],
            user["email"],
            user["stripe_customer_id"],
        ),
    }


@app.post("/api/billing/portal")
def portal(user: User) -> dict:
    """Open the Stripe billing portal."""
    return {"url": billing.portal_url(user["stripe_customer_id"])}


@app.post("/api/billing/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header("")) -> dict:
    """Receive Stripe subscription events."""
    billing.handle_webhook(await request.body(), stripe_signature)
    return {"ok": True}


@app.post("/api/billing/dev-plan")
def dev_plan(user: User, plan: str = "pro") -> dict:
    """Switch plans without Stripe (only when ALLOW_DEV_UPGRADE=1)."""
    if not billing.ALLOW_DEV_UPGRADE:
        raise HTTPException(status_code=404, detail="Not found")
    if plan not in auth.PLAN_LIMITS:
        raise HTTPException(status_code=400, detail="Unknown plan.")
    with db.connect() as conn:
        conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user["id"]))
    return {"ok": True, "plan": plan}


# ---------- Mock interview ----------


class QuestionRequest(BaseModel):
    """Request for the next mock interview question."""

    role: str
    level: str = "mid"
    interview_type: str = "behavioral"
    resume: str = ""
    job_description: str = ""
    previous: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """A candidate answer to be scored."""

    role: str
    question: str
    answer: str
    interview_type: str = "behavioral"


class AssistRequest(BaseModel):
    """Interviewer transcript for the practice coach."""

    role: str
    transcript: str
    resume: str = ""


@app.post("/api/question")
def next_question(req: QuestionRequest, user: User) -> dict:
    """Generate the next interview question."""
    auth.consume(user, "question")
    return ai.generate_json(ai.question_prompt(req), ai.QUESTION_SCHEMA)


@app.post("/api/feedback")
def feedback(req: FeedbackRequest, user: User) -> dict:
    """Score an answer, suggest improvements and save it to history."""
    if not req.answer.strip():
        raise HTTPException(status_code=400, detail="Write or speak an answer first.")
    result = ai.generate_json(
        ai.feedback_prompt(req.role, req.question, req.answer),
        ai.FEEDBACK_SCHEMA,
    )
    result["interview_type"] = req.interview_type
    result["id"] = save_attempt(
        user,
        "mock",
        req.role,
        req.question,
        req.answer,
        result,
    )
    return result


@app.post("/api/assist")
def assist(req: AssistRequest, user: User) -> dict:
    """Suggest talking points for the latest question in a transcript."""
    auth.consume(user, "assist")
    return ai.generate_json(
        ai.assist_prompt(req.role, req.transcript, req.resume),
        ai.ASSIST_SCHEMA,
    )


# ---------- Resume ----------


async def resume_text_from(resume_text: str, resume_file: UploadFile | None) -> str:
    """Read resume text from an uploaded PDF/TXT file, falling back to pasted text."""
    text = resume_text
    if resume_file is not None and resume_file.filename:
        data = await resume_file.read()
        if resume_file.filename.lower().endswith(".pdf"):
            try:
                reader = PdfReader(io.BytesIO(data))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail="Couldn't read that PDF.",
                ) from e
        else:
            text = data.decode("utf-8", errors="ignore")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Provide a resume file or text.")
    return text


@app.post("/api/resume-match")
async def resume_match(
    user: User,
    job_description: str = Form(...),
    resume_text: str = Form(""),
    resume_file: UploadFile | None = File(None),
) -> dict:
    """Compare a resume with a job description and save the result."""
    text = await resume_text_from(resume_text, resume_file)
    auth.consume(user, "match")
    result = ai.generate_json(ai.match_prompt(text, job_description), ai.MATCH_SCHEMA)
    result["id"] = save_attempt(user, "match", "", job_description[:300], "", result)
    return result


@app.post("/api/resume-tailor")
async def resume_tailor(
    user: User,
    job_description: str = Form(...),
    resume_text: str = Form(""),
    resume_file: UploadFile | None = File(None),
) -> dict:
    """Rewrite a full resume to target a job description."""
    text = await resume_text_from(resume_text, resume_file)
    auth.consume(user, "match")
    return ai.generate_json(ai.tailor_prompt(text, job_description), ai.TAILOR_SCHEMA)


# ---------- Coding interview ----------


class ProblemRequest(BaseModel):
    """Options for generating a coding problem."""

    language: str = "Python"
    difficulty: str = "medium"
    topic: str = ""
    previous: list[str] = Field(default_factory=list)


class HintRequest(BaseModel):
    """Current progress on a coding problem."""

    statement: str
    code: str = ""
    hints_given: int = 0


class ReviewRequest(BaseModel):
    """A coding solution to review."""

    title: str
    statement: str
    code: str
    language: str = "Python"


@app.post("/api/coding/problem")
def coding_problem(req: ProblemRequest, user: User) -> dict:
    """Generate an original coding interview problem."""
    auth.consume(user, "coding")
    return ai.generate_json(
        ai.problem_prompt(req.language, req.difficulty, req.topic, req.previous),
        ai.PROBLEM_SCHEMA,
    )


@app.post("/api/coding/hint")
def coding_hint(req: HintRequest, user: User) -> dict:  # noqa: ARG001 - requires sign-in
    """Give a progressive hint without revealing the solution."""
    return ai.generate_json(
        ai.hint_prompt(req.statement, req.code, req.hints_given),
        ai.HINT_SCHEMA,
    )


@app.post("/api/coding/review")
def coding_review(req: ReviewRequest, user: User) -> dict:
    """Review a solution and save it to history."""
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="Write some code first.")
    result = ai.generate_json(
        ai.review_prompt(req.statement, req.code, req.language),
        ai.REVIEW_SCHEMA,
    )
    result["language"] = req.language
    result["id"] = save_attempt(
        user,
        "coding",
        req.language,
        req.title,
        req.code,
        result,
    )
    return result


# ---------- History ----------


@app.get("/api/history")
def history(user: User, kind: str | None = None, limit: int = 100) -> list[dict]:
    """List the user's saved attempts, newest first."""
    query = "SELECT * FROM attempts WHERE user_id = ?"
    args: list = [user["id"]]
    if kind:
        query += " AND kind = ?"
        args.append(kind)
    query += " ORDER BY id DESC LIMIT ?"
    args.append(min(limit, 500))
    with db.connect() as conn:
        rows = conn.execute(query, args).fetchall()
    return [
        {
            "id": r["id"],
            "kind": r["kind"],
            "role": r["role"],
            "question": r["question"],
            "answer": r["answer"],
            "score": r["score"],
            "result": json.loads(r["result_json"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.delete("/api/history/{attempt_id}")
def delete_attempt(attempt_id: int, user: User) -> dict:
    """Delete one saved attempt."""
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM attempts WHERE id = ? AND user_id = ?",
            (attempt_id, user["id"]),
        )
    return {"ok": True}


@app.get("/api/stats")
def stats(user: User) -> dict:
    """Totals, average scores and recent score trend per practice type."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT kind, COUNT(*) AS n, AVG(score) AS avg FROM attempts WHERE user_id = ? GROUP BY kind",
            (user["id"],),
        ).fetchall()
        trend = conn.execute(
            """SELECT kind, score FROM (
                 SELECT kind, score, id FROM attempts
                 WHERE user_id = ? AND score IS NOT NULL ORDER BY id DESC LIMIT 60
               ) ORDER BY id""",
            (user["id"],),
        ).fetchall()
    by_kind = {
        r["kind"]: {
            "count": r["n"],
            "average": round(r["avg"], 1) if r["avg"] is not None else None,
        }
        for r in rows
    }
    series: dict[str, list[int]] = {}
    for r in trend:
        series.setdefault(r["kind"], []).append(r["score"])
    return {"by_kind": by_kind, "trend": series}


# ---------- Pages ----------


@app.get("/healthz")
def healthz() -> dict:
    """Health check."""
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    """Serve the landing page."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
