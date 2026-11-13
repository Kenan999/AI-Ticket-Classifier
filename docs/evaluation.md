# Evaluation

How we measure the ticket classifier, what the numbers mean, and what is
still missing. For commands, see the Evaluation section in the README.

## Scope

The evaluation lives in `evaluation/` and only ever *reads* the backend:

- `evaluate.py` — test tickets, measurement, metrics, CSV export
- `dashboard.py` — Streamlit view of the results

It imports `predict_ticket` from `backend/classifier.py` and
`classify_with_gemini` from `backend/llm_classifier.py`. No backend file is
modified, no Flask app is started and no SQLite database is touched.

## Test data (current state)

Five simple synthetic test tickets, one per category (Returns, Shipping,
Billing, Account, Technical), written by hand.

**Every score is currently 1.00. That is a property of the test set, not of
the classifier.** The tickets contain the exact keywords the rule baseline
looks for, so it cannot fail them. The numbers prove that the measurement
pipeline works; they say nothing about real customer tickets.

Replacing these with real labelled data is the single most valuable next
step. Until then, treat every chart on the dashboard as a smoke test.

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

| Provider | Classifier | Prompt | Output file |
|---|---|---|---|
| `baseline` | `predict_ticket` (keyword rules) | none | `results/evaluation/evaluation_v0.csv` |
| `gemini` | `classify_with_gemini` | the existing backend prompt | `results/evaluation/evaluation_gemini.csv` |

Each provider writes its own file so one run never overwrites the other and
the dashboard can show both side by side. The files are git-ignored runtime
artefacts; run the evaluation yourself after cloning.

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
an error message. `backend/.env` is git-ignored. Only the synthetic test
tickets are sent to Google — no customer data.

## Dashboard

`python -m streamlit run evaluation/dashboard.py` shows the selected
provider's KPIs, per-category results across versions, a comparison chart
with target lines (set in `dashboard.py`, not yet agreed in the team), the
prompt behind each version, all tickets and the misclassifications.

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

- Real labelled test data (currently five simple synthetic test tickets)
- Prompt variants V1–V3, once a prompt can be passed in
