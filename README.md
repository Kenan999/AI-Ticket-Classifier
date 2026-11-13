# AI Ticket Classifier — Backend

Python backend for an AI-assisted customer-support ticket classifier. It provides a Flask API to receive tickets, classify them with a transparent keyword-based baseline, suggest customer replies, and route uncertain cases for human review. Tickets are stored locally in SQLite, and review decisions are recorded in CSV.

The project also includes Bitext dataset download, loading, and preprocessing modules for future model training and evaluation. **The default classifier is rule-based; the optional Gemini adapter can be enabled with server-side credentials.** This is a local development backend and is not yet configured for public deployment.

## Dataset preparation

After installing `requirements.txt`, run `python backend/prepare_data.py` once
at setup/deployment. It downloads and SHA-256-verifies the pinned Bitext CSV,
then prepares `data/processed/train.csv`, `validation.csv`, and `test.csv`.
Repeated runs verify the source and skip unchanged processed outputs. Run this
as a deployment step, **not** on each API request. `data/` stays outside Git.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

`.venv/` stays outside Git. Activate it in every new terminal before running
any of the commands below.

## Local API and tests

Install dependencies with `python -m pip install -r requirements.txt` and start
`python backend/app.py` (defaults to `127.0.0.1:8001`).

- `GET /health`: health check.
- `POST /classify`: accepts JSON `{"text":"..."}`, classifies and stores a ticket.
- `GET /cases`: lists all saved tickets, newest first, with their current
  category, confidence, status and review fields. Empty database returns `[]`.
- `GET /case/<ticket_id>`: retrieves a saved ticket.
- `POST /review`: approves or corrects a ticket with an explicit human decision;
  writes review feedback to CSV and the updated ticket to SQLite.

## Evaluation

`evaluation/` measures the classifier against a small fixed set of labelled
tickets. It imports the backend directly — no API, database or frontend — and
never modifies backend files.

```bash
python -m evaluation.evaluate                     # rule baseline, offline
python -m evaluation.evaluate --provider gemini
python -m streamlit run evaluation/dashboard.py   # 127.0.0.1:8501
```

The Gemini run reuses `classify_with_gemini` with its existing system prompt
and needs `GEMINI_API_KEY` in `backend/.env` (copy `backend/.env.example`).
Each provider writes its own file, `results/evaluation/evaluation_v0.csv` or
`evaluation_gemini.csv`. Those are runtime artefacts, are git-ignored and must
not be committed, so run the evaluation once yourself before opening the
dashboard. A Gemini call that fails is recorded as an error and counted as
wrong; it does **not** fall back to the rule baseline, because a mixed result
would not be measurable.

The current test set is five simple synthetic test tickets, so **both**
providers currently score 1.00. Each provider is evaluated separately and has
its own result file. The numbers show that the measurement works, not that a
classifier is good. See [evaluation details](docs/evaluation.md) for the
method, the metrics and the open points.

## Tests

Run isolated tests with `python3 -m unittest discover -s tests -v`.
Cases are stored in `results/cases.sqlite` and review feedback in
`results/reviews.csv` by default; these runtime files must not be committed.
By default classification uses the keyword baseline. See [optional LLM integration](docs/llm_integration.md) for Gemini configuration. The
`Backend` branch is for development; push, open a PR, test/review and merge
into `main` for the existing deployment workflow. This checkout is not live.
