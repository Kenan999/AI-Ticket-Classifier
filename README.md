# AI Ticket Classifier — Backend

Python backend for an AI-assisted customer-support ticket classifier. It provides a Flask API to receive tickets, classify them with a transparent keyword-based baseline, suggest customer replies, and route uncertain cases for human review. Tickets are stored locally in SQLite, and review decisions are recorded in CSV.

The project also includes Bitext dataset download, loading, and preprocessing modules for future model training and evaluation. **The default classifier is rule-based; the optional Gemini adapter can be enabled with server-side credentials.** This is a local development backend and is not yet configured for public deployment.

## Dataset preparation

After installing `requirements.txt`, run `python backend/prepare_data.py` once
at setup/deployment. It downloads and SHA-256-verifies the pinned Bitext CSV,
then prepares `data/processed/train.csv`, `validation.csv`, and `test.csv`.
Repeated runs verify the source and skip unchanged processed outputs. Run this
as a deployment step, **not** on each API request. `data/` stays outside Git.

## Local API and tests

Install dependencies with `python3 -m pip install -r requirements.txt` and start
`python3 backend/app.py` (defaults to `127.0.0.1:8001`).

- `GET /health`: health check.
- `POST /classify`: accepts JSON `{"text":"..."}`, classifies and stores a ticket.
- `GET /cases`: lists all saved tickets, newest first, with their current
  category, confidence, status and review fields. Empty database returns `[]`.
- `GET /case/<ticket_id>`: retrieves a saved ticket.
- `POST /review`: approves or corrects a ticket with an explicit human decision;
  writes review feedback to CSV and the updated ticket to SQLite.

## Evaluation (V0)

`evaluation/evaluate.py` measures the classifier against a small fixed set of
labelled tickets. It imports `predict_ticket` directly, so no API, database or
frontend is involved, and it never modifies backend files. Run it from the
project root with `python3 -m evaluation.evaluate`. It prints accuracy,
per-category precision/recall/F1, macro-F1 and any misclassifications, and
writes one row per ticket to `results/evaluation/evaluation_v0.csv`.
That file is a runtime artefact and must not be committed.

The planned Streamlit dashboard needs `streamlit` (tested with 1.67.0). It is
**not** part of `requirements.txt` yet — install it separately while the
dashboard is still experimental:
`python3 -m pip install streamlit`. If the dashboard becomes permanent, move
the dependency into a requirements file; if it is dropped, remove this note.

## Tests

Run isolated tests with `python3 -m unittest discover -s tests -v`.
Cases are stored in `results/cases.sqlite` and review feedback in
`results/reviews.csv` by default; these runtime files must not be committed.
By default classification uses the keyword baseline. See [optional LLM integration](docs/llm_integration.md) for Gemini configuration. The
`Backend` branch is for development; push, open a PR, test/review and merge
into `main` for the existing deployment workflow. This checkout is not live.
