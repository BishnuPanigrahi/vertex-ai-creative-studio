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
"""Gemini prompts and structured-output schemas."""

import json
import logging
import os
from functools import lru_cache
from typing import Protocol

from fastapi import HTTPException
from google import genai
from google.genai import types

PROJECT_ID = os.environ.get("PROJECT_ID")
LOCATION = os.environ.get("LOCATION", "global")
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")

logger = logging.getLogger(__name__)

STR = {"type": "STRING"}
INT = {"type": "INTEGER"}
STR_LIST = {"type": "ARRAY", "items": STR}


def _obj(**props: dict) -> dict:
    return {"type": "OBJECT", "properties": props, "required": list(props)}


QUESTION_SCHEMA = _obj(question=STR, what_it_tests=STR)
FEEDBACK_SCHEMA = _obj(
    score=INT,
    strengths=STR_LIST,
    improvements=STR_LIST,
    stronger_answer=STR,
    follow_up_question=STR,
)
ASSIST_SCHEMA = _obj(detected_question=STR, talking_points=STR_LIST)
MATCH_SCHEMA = _obj(
    match_score=INT,
    matched_skills=STR_LIST,
    missing_skills=STR_LIST,
    bullet_rewrites=STR_LIST,
    cover_letter=STR,
)
TAILOR_SCHEMA = _obj(resume_markdown=STR)
PROBLEM_SCHEMA = _obj(
    title=STR,
    statement=STR,
    examples=STR_LIST,
    constraints=STR_LIST,
    starter_code=STR,
)
HINT_SCHEMA = _obj(hint=STR)
REVIEW_SCHEMA = _obj(
    score=INT,
    correctness=STR,
    time_complexity=STR,
    space_complexity=STR,
    issues=STR_LIST,
    improved_code=STR,
)


class QuestionLike(Protocol):
    """Fields needed to write a question prompt."""

    role: str
    level: str
    interview_type: str
    resume: str
    job_description: str
    previous: list[str]


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


def question_prompt(req: QuestionLike) -> str:
    """Prompt for the next mock interview question."""
    asked = "\n".join(f"- {q}" for q in req.previous) or "(none)"
    return f"""You are an experienced interviewer for a {req.level}-level {req.role} role.
Ask ONE {req.interview_type} interview question. Do not repeat these questions:
{asked}

Candidate resume (may be empty):
{req.resume[:6000]}

Job description (may be empty):
{req.job_description[:6000]}

Tailor the question to the resume and job description when they are provided."""


def feedback_prompt(role: str, question: str, answer: str) -> str:
    """Prompt for scoring an answer."""
    return f"""You are an interview coach evaluating a candidate for a {role} role.
Question: {question}
Candidate answer: {answer}

Score the answer from 1 to 10. List 2-3 specific strengths and 2-3 concrete improvements
(structure such as STAR, specificity, measurable impact, clarity). Write a stronger version
of the answer in the candidate's voice, keeping their real facts and not inventing
achievements. Finally, write the probing follow-up question a real interviewer would ask
next based on this answer."""


def assist_prompt(role: str, transcript: str, resume: str) -> str:
    """Prompt for practice-coach talking points."""
    return f"""You are a practice coach listening to a mock interview for a {role} role.
Here is the recent transcript of what the interviewer said:
{transcript[-4000:]}

Candidate resume (may be empty):
{resume[:6000]}

Identify the most recent question and give 3-5 short talking points the candidate could
use to structure their answer. Keep each point under 20 words."""


def match_prompt(resume: str, job_description: str) -> str:
    """Prompt for resume vs job description analysis."""
    return f"""Compare this resume with the job description.
Give a match score from 0 to 100, the skills that match, the important skills that are
missing, 3-5 rewritten resume bullets that better target the role (using only facts from
the resume), and a concise cover letter of under 250 words.

Resume:
{resume[:12000]}

Job description:
{job_description[:8000]}"""


def tailor_prompt(resume: str, job_description: str) -> str:
    """Prompt for a full tailored resume."""
    return f"""Rewrite this resume in Markdown so it targets the job description.
Keep every fact truthful: do not invent employers, titles, dates, degrees or metrics.
Reorder and rephrase to emphasise relevant experience, use strong action verbs, and
include a short professional summary and a skills section.

Resume:
{resume[:12000]}

Job description:
{job_description[:8000]}"""


def problem_prompt(
    language: str,
    difficulty: str,
    topic: str,
    previous: list[str],
) -> str:
    """Prompt for a coding interview problem."""
    seen = "\n".join(f"- {t}" for t in previous) or "(none)"
    return f"""Create an original {difficulty} coding interview problem about {topic or "any common topic"}.
Do not reuse these titles:
{seen}

Give a short title, a clear problem statement, 2-3 examples (input, output and a brief
explanation), the constraints, and starter code in {language} with a function signature
and no solution."""


def hint_prompt(statement: str, code: str, hints_given: int) -> str:
    """Prompt for a progressive coding hint."""
    return f"""A candidate is solving this interview problem:
{statement[:4000]}

Their current code:
{code[:6000]}

They have already received {hints_given} hints. Give the next hint only: one or two
sentences that nudge them forward without writing the solution. Get more specific as the
hint count grows."""


def review_prompt(statement: str, code: str, language: str) -> str:
    """Prompt for reviewing a coding solution."""
    return f"""Review this {language} solution to a coding interview problem as a strict interviewer.
Problem:
{statement[:4000]}

Solution:
{code[:8000]}

Score from 1 to 10, describe whether it is correct (mention failing edge cases), give the
time and space complexity, list concrete issues, and provide an improved solution."""
