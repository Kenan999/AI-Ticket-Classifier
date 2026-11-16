# Evaluation

How we measure the ticket classifier, what the numbers mean, and what is
still missing. For commands, see the Evaluation section in the README.

## Scope

The evaluation lives in `evaluation/` and only ever *reads* the backend:

- `evaluate.py` — sampling, measurement, metrics, CSV export
- `dashboard.py` — Streamlit view of the results

It imports `predict_ticket` and `dataset_label_for` from
`backend/classifier.py`, `load_dataset` from `backend/data_loader.py` and
`classify_with_gemini` from `backend/llm_classifier.py`. No backend file is
modified, no Flask app is started and no SQLite database is touched. The
dataset CSVs are read only — the sampling happens in memory, so no extra
dataset file is ever written.

## Test data

The prepared Bitext splits in `data/processed/`, produced by
`python backend/prepare_data.py`. Nine labels, 200 rows per label in both
`validation.csv` and `test.csv` (1,800 rows each). The evaluation only ever
reads them.

### Ground truth

**The dataset labels are the reference, not the classifier's categories.**
The app answers in its own seven categories, so each answer is translated to a
dataset label before it is compared:

| App category | Dataset label |
|---|---|
| Shipping | SHIPPING |
| Billing | PAYMENT |
| Account | ACCOUNT |
| Orders | ORDER |
| Returns, Technical, General | *none* |

The translation is read from `dataset_label_for` in `backend/classifier.py`,
not maintained here, so it follows the backend automatically.

An answer with no dataset label can never match and is counted as wrong. Those
answers get no row of their own in the per-label table: macro-F1 is averaged
over the nine real labels, never over invented ones.

Five of the nine labels — CONTACT, DELIVERY, FEEDBACK, INVOICE, REFUND — have
no category at all, so every ticket carrying them is wrong by construction.
That is a real finding about coverage, not a measurement error, and it is
stated on the dashboard.

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
| `gemini` | `classify_with_gemini` | the existing backend prompt |

Every combination of mode and provider writes its own file, named
`{number}_{mode}_{provider}.csv` — for example
`results/evaluation/01_smoke_v0.csv`. The leading number keeps the files in
mode order in the folder. No run ever overwrites another, and the dashboard
can show providers side by side. The files are git-ignored runtime artefacts;
run the evaluation yourself after cloning.

### Design decisions

**Gemini failures are recorded, not hidden.** If a call times out or returns
an unusable answer, the ticket gets the category `FEHLER`, the reason goes
into the `error` column, and it counts as wrong. The run continues with the
remaining tickets.

`backend/app.py` deliberately falls back to the rule baseline in that case,
which is right for serving traffic. For a *measurement* it would be wrong: the
result would be a mixture of two classifiers and no longer tell us what we
measured.

**The environment is read directly.** `evaluate.py` parses `backend/.env`
itself and accepts only `GEMINI_API_KEY`, `GEMINI_MODEL`,
`LLM_TIMEOUT_SECONDS` and `LLM_CATEGORIES`. Importing `backend/app.py` would
start Flask and create a SQLite file as an import side effect.

**The API key is read from the backend's `.env` and used only for the
request.** It is passed to the Gemini endpoint as the `x-goog-api-key`
header, and is never logged, printed, written to a result file or included in
an error message. `backend/.env` is git-ignored. Only Bitext ticket texts are
sent to Google — a public dataset under CDLA-Sharing-1.0, no customer data.

## Dashboard

`python -m streamlit run evaluation/dashboard.py` shows the KPIs for the
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

The dashboard reserves columns for three prompt variants. They are empty on
purpose — no placeholder numbers are ever shown.

They cannot be filled yet: `classify_with_gemini` builds its system prompt
inside the function (`backend/llm_classifier.py:54-66`) and takes no prompt
argument, so only one prompt can be measured. How to enable this is still to
be agreed in the team.

## Open points

- Five of the nine dataset labels have no category in the classifier
  (CONTACT, DELIVERY, FEEDBACK, INVOICE, REFUND). A ticket is with the
  backend owner.
- Prompt variants V1–V3, once a prompt can be passed in
