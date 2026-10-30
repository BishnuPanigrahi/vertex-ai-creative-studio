# Poised: AI Interview Coach

An original AI interview-preparation web app built on Gemini (Vertex AI). It has a
marketing landing page plus a working practice app with three tools:

| Tool | What it does | Endpoint |
| --- | --- | --- |
| Mock interview | Generates role/level/type-specific questions (tailored to your resume and job post), accepts typed or spoken answers, and returns a score, strengths, improvements and a stronger answer. | `POST /api/question`, `POST /api/feedback` |
| Practice coach | Listens via the browser's speech recognition while someone plays the interviewer and suggests talking points for the latest question. | `POST /api/assist` |
| Resume match | Compares a PDF/TXT resume to a job description: match score, matched/missing skills, rewritten bullets and a cover letter. | `POST /api/resume-match` |

"Poised" is a placeholder brand: change the name in `static/index.html`, `static/app.html`
and the colours in the `:root` block of `static/styles.css`.

## Run locally

```bash
cd experiments/interview-copilot
pip install -r requirements.txt
gcloud auth application-default login
export PROJECT_ID=your-gcp-project
export LOCATION=global            # optional
export MODEL_ID=gemini-2.5-flash  # optional
uvicorn server:app --reload --port 8080
```

Open http://localhost:8080 for the landing page and http://localhost:8080/app.html for the app.
Voice input works best in Chrome or Edge.

## Deploy to Cloud Run

```bash
gcloud run deploy poised --source . --region us-central1 \
  --set-env-vars PROJECT_ID=your-gcp-project --allow-unauthenticated
```

The Cloud Run service account needs the `Vertex AI User` role.

## Ideas for next steps

- Sign-in (Firebase Auth / Identity Platform) and saving sessions to Firestore
- Stripe checkout behind the pricing buttons
- Coding-interview tab with an in-browser editor
- Gemini Live API for lower-latency, full-duplex voice mock interviews
