# AI Ticket Classifier — Backend

Python backend for an AI-assisted customer-support ticket classifier. It provides a Flask API to receive tickets, classify them with a transparent keyword-based baseline, suggest customer replies, and route uncertain cases for human review. Tickets are stored locally in SQLite, and review decisions are recorded in CSV.

The project also includes Bitext dataset download, loading, and preprocessing modules for future model training and evaluation. **The default classifier is rule-based; optional Gemini and OpenAI adapters can be enabled with server-side credentials.** This is a local development backend and is not yet configured for public deployment.

## Dataset preparation

After installing `requirements.txt`, run `python backend/prepare_data.py` once
at setup/deployment. It downloads and SHA-256-verifies the pinned Bitext CSV,
then prepares `data/processed/train.csv`, `validation.csv`, and `test.csv`.
Repeated runs verify the source and skip unchanged processed outputs. Run this
as a deployment step, **not** on each API request. `data/` stays outside Git.

Preparation excludes CANCEL and SUBSCRIPTION, removes template placeholders,
then deduplicates messages before splitting. The result contains nine dataset
labels: 18,291 training messages, 1,800 validation messages and 1,800 test
messages (200 per label in each evaluation split). These dataset labels do not
replace the app's seven categories. Map the label sets explicitly before
comparing app predictions against this dataset. See
[dataset preparation details](docs/dataset_comparison.md).

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
- `GET /providers`: list provider IDs, display labels, configuration status and the default provider; never returns keys or calls a cloud API.
- `POST /classify`: accepts JSON `{"text":"...","provider":"openai"}`, classifies and stores a ticket. `provider` is optional: `baseline`, `openai` or `gemini`.
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
By default classification uses the keyword baseline. Set `LLM_PROVIDER=gemini`
or `LLM_PROVIDER=openai` in the backend process environment to use a cloud
provider. Gemini reads `GEMINI_API_KEY` and `GEMINI_MODEL` (default
`gemini-3.1-flash-lite`); OpenAI reads `OPENAI_API_KEY` and `OPENAI_MODEL`
(default `gpt-4.1-mini`). Deployment supplies these settings at runtime;
keep real keys out of source control and the frontend. OpenAI's key is read
only from the process environment. See
[optional LLM integration](docs/llm_integration.md) for additional Gemini settings.
When `provider` is omitted, the deployment default and existing local fallback
behavior are retained. An explicit provider applies only to that request: it
never changes other users' selections or the server environment. Explicit cloud
selection returns HTTP 503 (`provider_not_configured`) when the key is missing,
or HTTP 502 (`provider_unavailable`) if the call fails; no case is saved and no
other provider is substituted. Invalid selections return HTTP 400.
Successful cases include `requested_provider`, actual `provider`, `fallback_used`
and `model_version`; these fields are persisted. Older stored cases may lack the
new fields. `baseline` means local keyword rules, not a local LLM.

For a future frontend selector, fetch `GET /providers`, display the labels, and
send the selected ID in each `POST /classify`. `configured` only indicates that
a key is present, not that it is valid or the service is reachable. Keep API keys
and model settings on the server. Only `text` and optional `provider` are
accepted in classification requests; other fields return HTTP 400
(`unsupported_fields`). The deployment owner controls model names, credentials,
timeout and categories through the server environment. There is no API to change
these settings or prompts. See the [model and prompt reference](docs/llm_integration.md).
This contract is implemented only in the
backend development copy: frontend controls and deployment gateway routing for
`/providers` still need separate integration before public use.
The automated tests simulate cloud responses and do not validate live API access.
The `Backend` branch is for development; push, open a PR, test/review and merge
into `main` for the existing deployment workflow. This checkout is not live.

## Downloaded development starter

When using the shared backend during frontend development, keep the downloaded
`developer_client.py` in the project root. Git ignores that local file; do not
force-add it or commit access tokens. Follow the team setup guide for the local
connection workflow. Updating this ignore rule does not change the backend or
deploy the frontend.

## Use the deployed backend while developing the frontend

Use the ticket system's **Project Links → Set up local testing** guide.
Download the latest `developer_client.py` into your frontend checkout's root
and create your own one-hour access token. With the updated frontend runtime
configuration in place, run:

```sh
python3 developer_client.py --frontend public --port 8015
```

For a checkout whose website folder is named `frontend`, use `--frontend frontend`.
Paste the token at the hidden prompt, then open the printed local URL. The
starter supplies the API address automatically through `runtime-config.js`;
there is no manual edit to `app.js`. This requires a frontend checkout that includes `runtime-config.js`;
update your frontend branch before using this workflow.

The usual startup remains unchanged. This separate testing command connects
the local frontend to the deployed backend; you do not start a local backend.
API keys stay on the server and the token stays in the starter process. Requests
use shared live cases, including review changes. Use fictional messages.
Stop with Control-C. If the token expires, create another and restart.
If the port is busy, choose another with `--port`; the API address follows it.
Do not commit the downloaded starter or access tokens.

## Case timestamps, database metadata and filters

The development backend adds `created_at`, `updated_at`, `category`, `status`
and `confidence` columns to the existing SQLite `cases` table. On startup,
the migration runs transactionally and can be repeated. Existing JSON payloads
and ticket IDs are preserved; category/status/confidence are extracted from them.
Invalid legacy JSON aborts and rolls back the migration rather than deleting data.
Before deploying this migration, take a consistent SQLite backup. No deployment
or production migration is performed by this source change.

New cases receive UTC ISO-8601 timestamps. Reviews preserve `created_at`, update
`updated_at` and synchronize category/status columns with the JSON payload.
Legacy cases have unknown timestamps (`null` in API responses); reviewing one
sets only its update time. Historical creation dates are never invented.

`GET /cases` still returns a JSON array, now ordered by creation time descending.
Legacy cases with unknown dates come last, ordered by their existing row IDs.
Equal creation times use row IDs as a stable tie-breaker. Review updates no longer
replace database rows or reorder them by creation time.

Optional exact-match filters can be combined:

```text
GET /cases?status=reviewed&category=Technical
```

Statuses are `classified`, `human_review` or `reviewed`. Categories match exactly;
unmatched categories return an empty list. Empty categories, repeated parameters
and unsupported parameters return 400. Filters use SQL parameters; category,
status and creation time have indexes. Detail, list and classify responses expose
both timestamps. The review response keeps its existing contract; reload the case
to obtain its updated timestamps.

These filters are implemented in the development API only. The deployed gateway
and downloaded local-testing proxy currently reject query parameters and have not
been changed. No frontend controls or production changes are included here.
