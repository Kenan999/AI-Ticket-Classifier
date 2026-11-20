# Observation

Observation records what happened during an LLM request: source, model, prompt,
response or error, duration, token usage, estimated cost and retries. Evaluation
continues to measure prediction quality; its scores and saved results are unchanged.

## Automatic recording

The local ticket API and Evaluation inside **AI Operations** are connected.
Recording is controlled by `backend/observation/config.json`:

```json
"recording": {
  "enabled": true,
  "sources": ["application", "evaluation"],
  "sqlite_timeout_seconds": 0.05,
  "max_content_bytes": 65536
}
```

Settings are read when a ticket request or Evaluation run begins. Set `enabled`
to false to stop new recording, or remove a source from `sources`. Existing data
is retained. `OBSERVATION_CONFIG` can select an alternative config for embedding
or tests; the dashboards and receiver still use their normal config.

- Each actual provider HTTP attempt creates one row, including failed attempts.
  Retries share a logical call and run; a failed attempt remains visible even
  when the retry succeeds.
- Ticket requests link to their saved ticket ID and fallback outcome.
- An Evaluation run groups its individual requests/batches and retries under
  one run ID, with the prompt version and ticket IDs. A batch is one provider
  request, not one request per ticket.
- The original provider payload and response are captured. A successful HTTP
  response is marked as failed if the adapter rejects its classification.
- The actual requested model, returned model (when supplied), prompt hash,
  endpoint, safe response headers, usage and timing are included.
- Known credential fields and the request's API key are removed. Payloads over
  the configured size are replaced with a marked, bounded preview. Ticket
  content is still included; this is not a general personal-data anonymizer.
- SQLite writes use a short lock timeout. Storage/config failures generate a
  warning and do not change classification results or retry decisions. A failed
  write can leave a missing or unfinished observation.
- Local keyword classification, metadata lookups and failures before any
  provider request do not create LLM request rows.

The connection lives in the shared LLM transport and Observation integration
hooks. The Flask app installs the ticket scope; the shared AI Operations entry
point installs the Evaluation scope and batch validation wrapper once. No files
in the Evaluation folder are modified. Context-local state separates concurrent
requests and dashboard sessions.

The standalone Evaluation script/dashboard does **not** install that scope.
Use AI Operations for recorded evaluation runs, or explicitly call
`backend.observation.integration.install_evaluation()` before importing the
runner in another entry point. Direct adapter users can wrap calls in
`backend.observation.tracing.run_scope("application")`.

## Local startup

From the project root, using the project's Python environment:

```sh
python -m backend.app
(cd backend && python -m streamlit run ai_operations.py --server.port 8501)
```

Evaluation opens by default; select Observation in the same top navigation.
After a classification or evaluation run, refresh Observation to see the new
records. No external Observation server is needed for automatic recording:
both entry points write to the configured local SQLite store.

The default database remains at `results/observation/observation.sqlite3`.
Relative paths resolve against the project root. Existing tables and records
are retained. Importing Observation modules alone creates no database.

## Manual receiver and tests

The optional HTTP receiver is still available:

```sh
python -m backend.observation.service
```

Its host and port come from config (default `127.0.0.1:8510`). The standalone
test dialog uses this receiver; automatic classification recording does not.

- `GET /health`: check the receiver and database.
- `POST /observations`: supply source, provider, model, request and optional run ID.
- `PATCH /observations/<id>`: attach response/error once; completed rows are immutable.

The receiver cleans known credential fields but does not know the originating
API key: callers must not send credentials or authentication headers.
The recording toggle controls automatic hooks, not explicit receiver submissions.

The standalone dashboard can also read the same database:

```sh
python -m streamlit run backend/observation/dashboard.py --server.port 8511
```

## Metrics and costs

The dashboard uses the recorded provider usage and the pricing table in config.
Each response stores the price snapshot used for its estimate. Unknown prices
or missing usage remain unknown, including failures; they are not counted as
free. Estimates are not invoices and do not infer free-tier allowances,
discounts or additional charges. Historical records are not repriced.

A run displays the elapsed span from its first recorded request to its last
completion, including waits between requests. Each request retains its own
duration. Runs containing any failed attempt retain the error status.

Integration tests exercise the real Flask/evaluation/classifier paths with
mock provider transport and temporary databases. They make no paid API calls
and do not insert test data into the normal Observation database.
