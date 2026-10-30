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
"""API tests for Poised with Gemini mocked out."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai
import billing
import server


def fake_generate(prompt: str, schema: dict) -> dict:
    """Return a schema-shaped response so endpoints can be tested offline."""
    values = {"INTEGER": 7, "STRING": "text", "ARRAY": ["item"]}
    return {k: values[v["type"]] for k, v in schema["properties"].items()}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(ai, "generate_json", fake_generate)
    with TestClient(server.app) as c:
        yield c


def signup(c: TestClient, email: str = "a@example.com") -> None:
    r = c.post("/api/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text


def test_api_requires_sign_in(client):
    assert client.post("/api/question", json={"role": "SWE"}).status_code == 401
    assert client.get("/api/me").status_code == 401


def test_signup_login_logout(client):
    signup(client)
    assert client.get("/api/me").json()["email"] == "a@example.com"
    dup = client.post(
        "/api/auth/signup",
        json={"email": "A@example.com", "password": "password123"},
    )
    assert dup.status_code == 409
    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401
    bad = client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "wrong-pass"},
    )
    assert bad.status_code == 401
    ok = client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "password123"},
    )
    assert ok.status_code == 200
    assert client.get("/api/me").status_code == 200


def test_signup_validation(client):
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "nope", "password": "password123"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "b@example.com", "password": "short"},
        ).status_code
        == 400
    )


def test_mock_interview_saves_history_and_stats(client):
    signup(client)
    q = client.post("/api/question", json={"role": "SWE"}).json()
    assert q["question"] == "text"
    fb = client.post(
        "/api/feedback",
        json={"role": "SWE", "question": "q", "answer": "a"},
    ).json()
    assert fb["score"] == 7
    assert fb["follow_up_question"] == "text"
    hist = client.get("/api/history").json()
    assert len(hist) == 1
    assert hist[0]["kind"] == "mock"
    assert client.get("/api/stats").json()["by_kind"]["mock"] == {
        "count": 1,
        "average": 7.0,
    }
    client.delete(f"/api/history/{hist[0]['id']}")
    assert client.get("/api/history").json() == []


def test_free_plan_limit_and_dev_upgrade(client, monkeypatch):
    signup(client)
    for _ in range(5):
        assert client.post("/api/question", json={"role": "SWE"}).status_code == 200
    assert client.post("/api/question", json={"role": "SWE"}).status_code == 402
    assert client.post("/api/billing/dev-plan").status_code == 404
    monkeypatch.setattr(billing, "ALLOW_DEV_UPGRADE", True)
    assert client.post("/api/billing/dev-plan?plan=pro").json()["plan"] == "pro"
    assert client.post("/api/question", json={"role": "SWE"}).status_code == 200


def test_users_cannot_see_each_others_history(client):
    signup(client, "a@example.com")
    client.post("/api/feedback", json={"role": "SWE", "question": "q", "answer": "a"})
    client.post("/api/auth/logout")
    signup(client, "b@example.com")
    assert client.get("/api/history").json() == []


def test_resume_and_coding(client):
    signup(client)
    m = client.post(
        "/api/resume-match",
        data={"job_description": "jd", "resume_text": "resume"},
    )
    assert m.json()["match_score"] == 7
    assert (
        client.post("/api/resume-match", data={"job_description": "jd"}).status_code
        == 400
    )
    client.post("/api/billing/dev-plan")  # disabled; stays on free
    assert (
        client.post(
            "/api/resume-tailor",
            data={"job_description": "jd", "resume_text": "r"},
        ).status_code
        == 402
    )
    p = client.post("/api/coding/problem", json={"language": "Python"}).json()
    assert p["starter_code"] == "text"
    assert (
        client.post("/api/coding/hint", json={"statement": "s"}).json()["hint"]
        == "text"
    )
    r = client.post(
        "/api/coding/review",
        json={"title": "t", "statement": "s", "code": "pass"},
    )
    assert r.json()["score"] == 7
    kinds = {h["kind"] for h in client.get("/api/history").json()}
    assert kinds == {"match", "coding"}


def test_profile_round_trip(client):
    signup(client)
    client.put(
        "/api/profile",
        json={"role": "PM", "level": "senior", "resume": "r", "job_description": "j"},
    )
    assert client.get("/api/me").json()["profile"]["role"] == "PM"


def test_billing_disabled_without_stripe(client):
    signup(client)
    assert client.post("/api/billing/checkout").status_code == 503


def test_delete_account(client):
    signup(client)
    assert client.delete("/api/account").status_code == 200
    ok = client.post(
        "/api/auth/login",
        json={"email": "a@example.com", "password": "password123"},
    )
    assert ok.status_code == 401
