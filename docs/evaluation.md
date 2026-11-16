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

`evaluation/prompts.py` is the shared source for both adapters. V1 is the
backend default. V2 and V3 initially use the same wording as V1, so they only
become distinct experiments after you edit their templates. The configured
category list is inserted when the prompt is rendered. The dashboard shows
metrics after a run produces a result CSV.

## Open points

- Five of the nine dataset labels have no category in the classifier
  (CONTACT, DELIVERY, FEEDBACK, INVOICE, REFUND). A ticket is with the
  backend owner.
- Define distinct V2 and V3 experiments and measure them on the validation split.
