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

## Local API and tests

Install dependencies with `python3 -m pip install -r requirements.txt` and start
`python3 backend/app.py` (defaults to `127.0.0.1:8001`).

- `GET /health`: health check.
- `GET /providers`: list provider IDs, display labels, configuration status and the default provider; never returns keys or calls a cloud API.
- `POST /classify`: accepts JSON `{"text":"...","provider":"openai"}`, classifies and stores a ticket. `provider` is optional: `baseline`, `openai` or `gemini`.
- `GET /cases`: lists all saved tickets, newest first, with their current
  category, confidence, status and review fields. Empty database returns `[]`.
- `GET /case/<ticket_id>`: retrieves a saved ticket.
- `POST /review`: approves or corrects a ticket with an explicit human decision;
  writes review feedback to CSV and the updated ticket to SQLite.

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
