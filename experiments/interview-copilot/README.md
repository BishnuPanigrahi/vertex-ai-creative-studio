# Poised: AI Interview Coach

An original AI interview-preparation web app built on Gemini (Vertex AI) and FastAPI.

## Features

| Area | What it does |
| --- | --- |
| Accounts | Email/password sign-up and sign-in (scrypt hashes, HTTP-only session cookies), saved defaults for role, level, resume and job description, and account deletion. |
| Mock interview | Questions tailored to role, level, interview type, resume and job post. Typed or spoken answers, an answer timer, a 1-10 score, strengths, improvements, a stronger answer and a realistic follow-up question you can answer next. |
| Voice mode | Reads each question aloud (speech synthesis), then starts the microphone automatically. |
| Coding interview | Original problems in 7 languages by difficulty and topic, a countdown timer, an editor with tab indent, progressive hints and a review with score, correctness, time/space complexity, issues and an improved solution. |
| Practice coach | Listens while someone plays the interviewer, detects questions and suggests talking points. |
| Resume & cover letter | PDF/TXT upload or pasted text: match score, matched/missing skills, rewritten bullets, a cover letter and a full tailored resume in Markdown (copy or download). |
| Progress | Average score and trend per practice type, full history with details, filter, delete and Markdown report export. |
| Plans & billing | Free daily limits (5 questions, 3 coding problems, 10 coach suggestions, 1 resume action) and an unlimited Pro plan via Stripe Checkout, billing portal and webhooks. |

"Poised" is a placeholder brand: change the name in `static/*.html` and the colours in the
`:root` block of `static/styles.css`. Plan limits live in `PLAN_LIMITS` in `auth.py`.

## Layout

```
server.py    FastAPI routes
ai.py        Gemini client, prompts and JSON response schemas
auth.py      passwords, sessions, plan limits
billing.py   Stripe checkout, portal and webhook
db.py        SQLite schema and connection helper
static/      landing page, sign-in page and app (plain HTML/CSS/JS)
tests/       pytest suite (Gemini mocked)
```

## Run locally

```bash
cd experiments/interview-copilot
pip install -r requirements.txt
gcloud auth application-default login
export PROJECT_ID=your-gcp-project
export ALLOW_DEV_UPGRADE=1   # optional: lets "Upgrade" switch plans without Stripe
uvicorn server:app --reload --port 8080
```

Open http://localhost:8080. Voice features work best in Chrome or Edge.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PROJECT_ID` | – | Google Cloud project for Vertex AI |
| `LOCATION` | `global` | Vertex AI location |
| `MODEL_ID` | `gemini-2.5-flash` | Gemini model |
| `DATABASE_PATH` | `./poised.db` | SQLite file |
| `COOKIE_SECURE` | `0` | Set to `1` when served over HTTPS |
| `APP_URL` | `http://localhost:8080` | Public URL, used for Stripe redirects |
| `STRIPE_SECRET_KEY` | – | Enables payments |
| `STRIPE_PRICE_ID` | – | Recurring price for Pro |
| `STRIPE_WEBHOOK_SECRET` | – | Verifies webhook events |
| `ALLOW_DEV_UPGRADE` | `0` | Plan switching without Stripe. Never enable in production. |

### Stripe

1. Create a product with a recurring price and copy its price ID.
2. Add a webhook endpoint at `${APP_URL}/api/billing/webhook` for `checkout.session.completed`,
   `customer.subscription.updated` and `customer.subscription.deleted`.
3. Enable the customer portal in the Stripe dashboard.

For local testing: `stripe listen --forward-to localhost:8080/api/billing/webhook`.

## Tests

```bash
pip install pytest httpx
python -m pytest
```

## Deploy to Cloud Run

```bash
gcloud run deploy poised --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars PROJECT_ID=your-gcp-project,COOKIE_SECURE=1,APP_URL=https://your-domain
```

The service account needs the `Vertex AI User` role. Cloud Run's filesystem is ephemeral,
so point `DATABASE_PATH` at a mounted volume (for example a Cloud Storage FUSE or Filestore
mount) with `--max-instances 1`. To scale out, move `db.py` to Cloud SQL or Firestore.
Keep Stripe keys in Secret Manager (`--set-secrets`).
