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
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from pydantic import BaseModel
from pypdf import PdfReader

PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = os.environ.get("LOCATION", "global")
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")
STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Poised")


@lru_cache(maxsize=1)
def client() -> genai.Client:
    """Return a shared Vertex AI Gemini client."""
    return genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)


def generate_json(prompt: str, schema: dict) -> dict:
    """Call Gemini with a JSON response schema and return the parsed result."""
    try:
        response = client().models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.7,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        logger.exception("Gemini request failed")
        raise HTTPException(status_code=502, detail=f"Model request failed: {e}") from e


class QuestionRequest(BaseModel):
    """Request for the next mock interview question."""

    role: str
    level: str = "mid"
    interview_type: str = "behavioral"
    resume: str = ""
    job_description: str = ""
    previous: list[str] = []


class FeedbackRequest(BaseModel):
    """A candidate answer to be scored."""

    role: str
    question: str
    answer: str


class AssistRequest(BaseModel):
    """Interviewer transcript for the practice coach."""

    role: str
    transcript: str
    resume: str = ""


QUESTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "question": {"type": "STRING"},
        "what_it_tests": {"type": "STRING"},
    },
    "required": ["question", "what_it_tests"],
}

FEEDBACK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "score": {"type": "INTEGER"},
        "strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
        "improvements": {"type": "ARRAY", "items": {"type": "STRING"}},
        "stronger_answer": {"type": "STRING"},
    },
    "required": ["score", "strengths", "improvements", "stronger_answer"],
}

ASSIST_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "detected_question": {"type": "STRING"},
        "talking_points": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["detected_question", "talking_points"],
}

MATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "match_score": {"type": "INTEGER"},
        "matched_skills": {"type": "ARRAY", "items": {"type": "STRING"}},
        "missing_skills": {"type": "ARRAY", "items": {"type": "STRING"}},
        "bullet_rewrites": {"type": "ARRAY", "items": {"type": "STRING"}},
        "cover_letter": {"type": "STRING"},
    },
    "required": [
        "match_score",
        "matched_skills",
        "missing_skills",
        "bullet_rewrites",
        "cover_letter",
    ],
}


@app.post("/api/question")
def next_question(req: QuestionRequest) -> dict:
    """Generate the next interview question."""
    asked = "\n".join(f"- {q}" for q in req.previous) or "(none)"
    prompt = f"""You are an experienced interviewer for a {req.level}-level {req.role} role.
Ask ONE {req.interview_type} interview question. Do not repeat these questions:
{asked}

Candidate resume (may be empty):
{req.resume[:6000]}

Job description (may be empty):
{req.job_description[:6000]}

Tailor the question to the resume and job description when they are provided."""
    return generate_json(prompt, QUESTION_SCHEMA)


@app.post("/api/feedback")
def feedback(req: FeedbackRequest) -> dict:
    """Score an answer and suggest improvements."""
    prompt = f"""You are an interview coach evaluating a candidate for a {req.role} role.
Question: {req.question}
Candidate answer: {req.answer}

Score the answer from 1 to 10. List 2-3 specific strengths and 2-3 concrete improvements
(structure such as STAR, specificity, measurable impact, clarity). Then write a stronger
version of the answer in the candidate's voice, keeping their real facts and not inventing
achievements."""
    return generate_json(prompt, FEEDBACK_SCHEMA)


@app.post("/api/assist")
def assist(req: AssistRequest) -> dict:
    """Suggest talking points for the latest question in a transcript."""
    prompt = f"""You are a practice coach listening to a mock interview for a {req.role} role.
Here is the recent transcript of what the interviewer said:
{req.transcript[-4000:]}

Candidate resume (may be empty):
{req.resume[:6000]}

Identify the most recent question and give 3-5 short talking points the candidate could
use to structure their answer. Keep each point under 20 words."""
    return generate_json(prompt, ASSIST_SCHEMA)


@app.post("/api/resume-match")
async def resume_match(
    job_description: str = Form(...),
    resume_text: str = Form(""),
    resume_file: UploadFile | None = File(None),
) -> dict:
    """Compare a resume with a job description."""
    text = resume_text
    if resume_file is not None and resume_file.filename:
        data = await resume_file.read()
        if resume_file.filename.lower().endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            text = data.decode("utf-8", errors="ignore")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Provide a resume file or text.")
    prompt = f"""Compare this resume with the job description.
Give a match score from 0 to 100, the skills that match, the important skills that are
missing, 3-5 rewritten resume bullets that better target the role (using only facts from
the resume), and a concise cover letter of under 250 words.

Resume:
{text[:12000]}

Job description:
{job_description[:8000]}"""
    return generate_json(prompt, MATCH_SCHEMA)


@app.get("/healthz")
def healthz() -> dict:
    """Health check."""
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    """Serve the landing page."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
