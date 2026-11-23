# Evaluation

How we measure the ticket classifier, what the numbers mean, and what is
still missing. For commands, see the Evaluation section in the README.

## Scope

The evaluation lives in `backend/evaluation/` and only ever *reads* the backend:

- `evaluate.py` — sampling, measurement, metrics, CSV export
- `dashboard.py` — Streamlit view of the results

It imports `predict_ticket` and `dataset_label_for` from
`backend/keyword_classifier.py`, `load_dataset` from `backend/data/data_loader.py` and
`classify_with_gemini` from `backend/llms/gemini.py`. No backend file is
modified, no Flask app is started and no SQLite database is touched. The
dataset CSVs are read only — the sampling happens in memory, so no extra
dataset file is ever written.

## Test data

The prepared Bitext splits in `data/processed/`, produced by
`python backend/data/prepare_data.py`. Nine labels, 200 rows per label in both
`validation.csv` and `test.csv` (1,800 rows each). The evaluation only ever
reads them.

### Ground truth

The dataset and classifier use the same nine labels. The evaluation reads
them through `dataset_label_for` in `backend/keyword_classifier.py`. A historical or
invalid prediction without an exact dataset label counts as wrong. Macro-F1
averages over the labels in the ground truth.

### Modes

Each mode draws a fixed sample with `random_state=42`. The rows are sorted by
`ticket_id` before and after drawing, so the sample depends only on file,
count and seed — never on the row order in the file. Every run and every
machine therefore measures exactly the same tickets, which is what makes two
prompt versions comparable.

| Mode | Source | Sample | Tickets | Purpose |
|---|---|---|---|---|
| `smoke` | `validation.csv` | 5 per label | 45 | does the measurement run? |
| `validation` | `validation.csv` | 20 per label | 180 | compare prompts |
| `final` | `test.csv` | all | 1,800 | independent acceptance |

`test.csv` is reserved for the final mode and is never used while choosing a
prompt.

### Current numbers (rule baseline)

| Mode | Accuracy | Macro-F1 |
|---|---|---|
| smoke | 0.33 | 0.31 |
| validation | 0.36 | 0.33 |
| final | 0.31 | 0.30 |

The three agree closely, which is the point of the smoke mode: 45 tickets
already predict what 1,800 will say. Precision is high wherever the baseline
commits to a category and recall is low — it falls back to `General` too
often rather than classifying wrongly.

## What is measured

| Metric | Meaning |
|---|---|
| Accuracy | share of tickets put in the right category |
| Precision | of all tickets predicted as X, how many really are X |
| Recall | of all tickets that really are X, how many were found |
| F1 | harmonic mean of precision and recall |
| Macro-F1 | unweighted mean of the per-category F1 values |

All values are between 0 and 1. Macro-F1 weights every category equally: a
category with two tickets counts as much as one with two hundred. A
classifier that is good at common categories and weak at rare ones therefore
scores lower on macro-F1 than on accuracy. It is reported as a decimal, not a
percentage: 0.87 does not mean "87 of 100 correct".

The metrics are computed in `evaluate.py` with plain Python — no
scikit-learn. At this size the arithmetic is a few lines, and it keeps the
dependency list unchanged.

## Providers

| Provider | Classifier | Prompt |
|---|---|---|
| `baseline` | `predict_ticket` (keyword rules) | none |
| `gemini` | `classify_with_gemini` | backend default |
| `gemini-v1` through `gemini-v3` | `classify_with_gemini` | selected version |
| `openai-v1` through `openai-v3` | `classify_with_openai` | selected version |

Each combination of mode, provider, and version has its own CSV. For example,
Gemini V2 validation writes `results/evaluation/02_validation_gemini_v2.csv`.
Every versioned row records `prompt_version`. Running the same combination
again replaces its previous result. The files are git-ignored runtime artefacts;
run the evaluation yourself after cloning.

### Design decisions

**Provider failures.** If a call times out or returns
an unusable answer, the ticket gets the category `FEHLER`, the reason goes
into the `error` column, and it counts as wrong. The run continues with the
remaining tickets.

`backend/app.py` deliberately falls back to the rule baseline in that case,
which is right for serving traffic. For a *measurement* it would be wrong: the
result would be a mixture of two classifiers and no longer tell us what we
measured.

`evaluate.py` reads an allowlist of provider keys, models, categories, and
timeout settings. Process environment variables take precedence over
`backend/.env`. The selected provider key is used only in its request header.
Evaluation sends Bitext dataset texts to the selected provider.

## Dashboard

`(cd backend && python -m streamlit run evaluation/dashboard.py)` shows the KPIs for the
selected provider and mode, per-label results across versions, a comparison
chart with target lines (set in `dashboard.py`, not yet agreed in the team),
the prompt behind each version, all tickets and the misclassifications.

Mode and provider are chosen in the sidebar. The note at the top names the
source file, the sample size and the labels the classifier cannot reach, so
the numbers are never read without that context.

Two notes for whoever works on it next:

- Streamlit reloads changed local modules on rerun. If a stale import error
  appears after editing `evaluate.py`, restart the server.
- Chart colours come from a validated palette. Blue/violet was rejected
  because the pair is not distinguishable with red-green colour blindness;
  blue/orange is used instead.

## Prompt versions V1–V3

`backend/llms/prompts.py` is the shared source for both adapters. V1 is the
backend default. V2 and V3 initially use the same wording as V1, so they only
become distinct experiments after you edit their templates. The configured
nine-label list and shared category guidance from `backend/keyword_classifier.py`
are inserted when the prompt is rendered. The dashboard shows metrics after
a run produces a result CSV.

## Open points

- Define distinct V2 and V3 experiments and measure them on the validation split.


## Proposed persistent background evaluation jobs (design only)

## Goal
An Evaluation job must survive Streamlit reruns, browser refreshes and browser closure. A user can request cancellation; Observation must distinguish `manually_stopped` from success, failure and unexpected interruption.

## Architecture
- **Streamlit UI**: submits a job, reads durable status and requests cancellation. It never owns the evaluation loop.
- **Job registry**: SQLite (`results/evaluation/jobs.sqlite3`) with WAL, busy timeout, atomic transactions and a unique `job_id`.
- **Worker**: independent local subprocess, launched with the current Python environment and a job ID. Worker reads immutable job parameters and writes progress and result checkpoints. Streamlit restart does not kill the worker.
- **Observation**: each model request retains a shared `run_id = job_id`; an explicit job-level lifecycle record tracks completion or cancellation. Request-level failures are not misrepresented as user cancellation.

## Job state machine
`queued -> running -> completed | failed | manually_stopped | interrupted`

`running -> stop_requested -> manually_stopped` after the current in-flight model call reaches a safe cancellation boundary. If the worker crashes after stop request, classify as interrupted unless the worker confirms stop. `stop_requested` must not be displayed as already stopped.

## Durable schema
`jobs(job_id PK, provider, mode, batch, prompt_version, status, created_at, started_at, updated_at, finished_at, worker_pid, completed_tickets, total_tickets, request_count, error_count, stop_requested_at, stop_confirmed_at, error_type, result_path, partial_path, config_snapshot_json)`.

Store only allowlisted configuration, never API keys, ticket text, or credentials. Use separate `job_events(job_id, sequence, timestamp, event_type, payload_json)` for an auditable state history. Add indexes on status and created_at.

## Worker protocol
1. UI validates dataset/provider, inserts a `queued` job and launches worker; enforce a single active job per selected configuration or an explicit concurrency limit.
2. Worker claims the job atomically, marks `running`, and loads the dataset and model settings snapshot.
3. Worker records progress/checkpoints after each ticket or completed batch, with atomic file replacement. Every request uses `job_id` for Observation grouping.
4. Before each new request/batch, worker checks `stop_requested_at`. On stop: flush checkpoint, mark `manually_stopped`, record time and completed/request counts, annotate Observation run.
5. On success: persist final CSV and mark `completed` only after file integrity checks. On failure: mark `failed` with sanitized error type.
6. On startup/status polling, detect stale workers by PID plus heartbeat; mark `interrupted` after a grace period. Never silently rerun jobs or duplicate provider calls.

## Refresh / Stop UI
- Reopen Evaluation: query latest active job and display status, progress, elapsed time, completed tickets and a **Stop evaluation** button.
- Stop action: atomic update to `stop_requested`; show **Stopping…** until worker acknowledges. Repeated stop clicks are idempotent.
- Poll state using Streamlit fragment auto-refresh or explicit refresh, without starting duplicate jobs.
- Completed/interrupted/failed/stopped jobs remain inspectable after refresh.

## Observation semantics
- Requests grouped by the same `job_id` represent one evaluation run; a loop icon appears only when there are multiple actual provider requests.
- Job-level `manually_stopped` event is explicit, including `stop_requested_at`, `stop_confirmed_at`, `completed_tickets` and `request_count`.
- Preserve already completed request records and partial results. A batch of many tickets in one HTTP request is **not** itself a loop.

## Safety / testing gates
- No provider calls in unit tests: mock workers and model transports.
- Test browser refresh during running job, Streamlit process restart, browser closure, stop during a slow call, repeated Stop, crash recovery, SQLite contention, and concurrent Start clicks.
- Confirm Observation records share job ID and distinguish manual stop from timeout or process crash.
- Test baseline, OpenAI/Gemini and local Qwen (single and batch) before replacing the current synchronous UI path.

## Implementation sequence
1. Job schema and state transitions with tests.
2. Worker CLI and atomic progress/checkpoint persistence.
3. Observation lifecycle integration and cancellation semantics.
4. Streamlit start/status/stop UI and refresh recovery.
5. Integration tests, then controlled cutover.

**Status:** design only; no background job implementation or migration has been performed.
