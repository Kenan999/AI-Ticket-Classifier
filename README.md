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
messages (200 per label in each evaluation split). Baseline, Gemini, and
OpenAI all use the same nine dataset labels. See
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

`evaluation/` measures the classifier against the prepared Bitext splits. It
imports the backend directly — no API, database or frontend — and never
modifies backend files or the dataset. Run `python backend/prepare_data.py`
first; the evaluation reads `data/processed/` and nothing else.

The **dataset labels are the ground truth**. Predictions use the exact
Bitext labels. Existing cases keep their saved categories, and legacy labels
without an exact match have no dataset label. Correct a legacy case to one
of the nine labels when submitting a new human review.

Three modes, each drawing a fixed sample with `random_state=42`, so every run
and every machine measures exactly the same tickets:

| Mode | Source | Sample | Purpose |
|---|---|---|---|
| `smoke` | `validation.csv` | 5 per label | does the measurement run? |
| `validation` | `validation.csv` | 20 per label | compare prompts |
| `final` | `test.csv` | all (200 per label) | independent acceptance |

```bash
python -m evaluation.evaluate                     # smoke, rule baseline
python -m evaluation.evaluate --mode validation
python -m evaluation.evaluate --mode final
python -m evaluation.evaluate --provider gemini-v1 --mode validation
python -m evaluation.evaluate --provider openai-v1 --mode validation
python -m streamlit run evaluation/dashboard.py   # 127.0.0.1:8501
```

Gemini and OpenAI reuse their backend adapters and the shared system prompts
in `evaluation/prompts.py`. V1 uses identical instructions for Gemini and OpenAI.
V2 and V3 are empty placeholders for future prompts; selecting either raises a
not-configured error before any provider call. The dashboard shows a prompt-entry
message and disables execution for those empty versions.
V1 and local rules can still use Smoke, Validation, and Final. Select a version with
`--provider gemini-v1` through `gemini-v3`, or `openai-v1` through `openai-v3`.
Set the matching `GEMINI_API_KEY` or `OPENAI_API_KEY` in the process environment
or `backend/.env`. A final run makes 1,800 requests to the selected provider.

Each combination of mode, provider, and prompt version writes its own CSV,
including the version used. The rules still write `results/evaluation/01_smoke_v0.csv`. Those are runtime artefacts, are
git-ignored and must not be committed, so run the evaluation once yourself
before opening the dashboard. A provider call that fails is recorded as an error
and counted as wrong; it does **not** fall back to the rule baseline, because a
mixed result would not be measurable.

Generate new results after switching to the nine-label classifier so
comparisons use the same taxonomy. See [evaluation details](docs/evaluation.md)
for the method and metrics.

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

The evaluation dashboard shows the rule baseline and explicit Gemini/OpenAI
V1–V3 entries. The duplicate Gemini Standard option is omitted.

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
GET /cases?status=reviewed&category=CONTACT
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


### Evaluation selection

Choose the test and dataset, then the prompt version and classification method:

- Smoke: 45 tickets sampled from validation.csv.
- Prompt validation: 180 tickets sampled from validation.csv.
- Final acceptance: all 1,800 held-out tickets from test.csv.

The sidebar shows the source filename and actual ticket count before execution.
Each test can use V1, V2 or V3 with Gemini or OpenAI. Empty prompts show a reminder,
disable execution and display no results. Local rules skip prompt selection.
Test selection keeps the established dataset sizes and result filenames, so existing
results remain available without mixing test datasets. Changing controls does not run
an evaluation; only the run button starts it.


### Evaluation rate-limit handling

The application and evaluations share the same provider retry helper (at most two
retries). App requests retain their short request-timeout budget. Evaluations use
`EVALUATION_RETRY_BUDGET_SECONDS=120` as the total per-ticket budget, while each
network attempt still uses `LLM_TIMEOUT_SECONDS`. Evaluations wait six seconds
between cloud tickets by default (`EVALUATION_REQUEST_INTERVAL_SECONDS=6`). These
evaluation settings can be set in the process environment or private backend .env.
Rules are not delayed. Provider Retry-After instructions are respected when they
fit the budget; exhausted quotas still fail immediately. Failures remain explicit
in each result's error field, never replaced with local-rule predictions. Pacing
is per evaluation process, not an account-wide quota guarantee. Avoid concurrent
runs using the same provider key. Existing result files are not changed by this.


### Evaluation batching

Dashboard and CLI now send cloud evaluation tickets in batches. The dashboard
checkbox switches between batch runs/results and the existing single-ticket runs.
The application API continues to classify one ticket per request.

Shared settings: `evaluation/config.py`, with separate Gemini and OpenAI model
profiles. No fixed ticket-count cap by default; a conservative 16,000 input
budget, 128 output tokens per ticket plus envelope overhead, and a context reserve.
Packing uses UTF-8 bytes plus overhead as a conservative sizing estimate, **not an
exact token count**. It does not attempt to fill the model's entire context window.
Unknown models require an explicit profile. Provider rate limits depend on the
account and are separate from context limits; batching does not remove quotas.

Only ticket text and generated IDs are sent; expected labels remain local.
Responses are matched by ID, and missing/duplicate/invalid or truncated responses
mark the entire affected batch as failed. No silent baseline fallback occurs.
Oversized tickets fail preflight before requests. Six-second pacing and the
existing retry budget apply between batches rather than between tickets.

Batch CSV names end in `_batch_v1.csv`; existing single-ticket result files remain
intact. Repeating the same batch/provider/prompt/test combination overwrites its
batch file. Batch context can affect predictions, so compare results separately.
V2/V3 remain blocked until prompts exist. Live smoke verification used three requests per provider: OpenAI completed all
45 tickets; Gemini was rate-limited. Generated results are not committed.

Model-limit sources: [OpenAI GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
and [Gemini 3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite).

The batch dashboard reports processed-ticket percentage, planned batches, actual
HTTP attempts (including retries), and failed-ticket count. 100% processed does
not mean 100% correct or successful. The latest run summary persists in the
browser session; it is separate from Accuracy and Macro-F1.

Evaluation retry timing is centralized in evaluation/config.py: the default total
retry budget is now 300 seconds per request/batch, with six seconds between
requests/batches. Environment overrides still take precedence. Interactive app
timeouts are unchanged. Provider-directed waits are honored within that budget;
longer waits report their duration and budget. This does not increase provider
quotas and still permits at most two retries.


Provider observations: Gemini model metadata is queried once per evaluation and
can reduce the configured input/output ceilings. If unavailable, the UI explicitly
labels the configured fallback. OpenAI's model metadata did not expose context
limits in our probe, so its documented profile remains necessary. Successful and
failed generation responses supply rate-limit headers when available; the next
batch waits for an advertised request/token reset if remaining capacity is too
small. Waits exceeding the evaluation budget are reported without sending that
batch. Headers are snapshots, not reservations, and concurrent clients can consume
the same quota. Missing headers are treated as unknown, never unlimited.

Batch count is now determined by text size and output reserve, without a fixed
20-ticket ceiling. UTF-8 sizing remains conservative and is not exact token
counting; Gemini countTokens is supported but not invoked by this implementation.
Metadata requests are counted separately from generation requests and retries.
Only metadata lookups were made while verifying this update, not new model runs.

Batch generation has a separate 60-second network timeout (override with
EVALUATION_BATCH_TIMEOUT_SECONDS); the normal app timeout stays unchanged.
Connection, timeout and invalid-response failures are reported separately.
Runs with only failed requests show unavailable quality metrics rather than
zero Accuracy/F1, and remain inspectable in the error table. Existing CSVs are
not changed. Provider quotas still apply and cannot be increased by this code.
