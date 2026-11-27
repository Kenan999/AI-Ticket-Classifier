# Optional LLM-based Ticket Classification

This integration is part of the **Backend development branch**, not the live
website. `GET /providers` lists the available provider IDs, display labels,
configuration status and the server default. The frontend can send
`{"text":"...","provider":"openai"}` to the existing `POST /classify` endpoint.
The optional provider is `baseline`, `openai` or `gemini`. The local baseline
uses keyword rules, not a local LLM. Keys are never returned to the frontend.
Configuration status indicates key presence only, not live API availability.

## How it works

1. Frontend sends a ticket and an optional provider to `POST /classify`.
2. Backend validates both fields. An explicit provider applies to this ticket
   only; otherwise `LLM_PROVIDER` selects the default. No global setting changes.
3. The selected cloud adapter receives the ticket, allowed categories and a
   server-only key. Its response must contain an allowed category and confidence.
4. Backend stores successful results in SQLite. The response includes
   `requested_provider`, actual `provider`, `fallback_used` and `model_version`.
   Low-confidence predictions go to Human Review. A human must confirm replies.
5. An explicit cloud choice returns HTTP 503 if its key is absent or HTTP 502
   if classification fails, without saving a case or silently switching provider.
   Invalid choices return HTTP 400. Requests that omit `provider` retain the
   existing fallback to local rules when the configured cloud provider fails.

The frontend selector and deployment gateway routing for `/providers` are
separate integration steps; this change implements the development backend.

No ticket data is sent to Gemini unless selected by the request or server default. **The Gemini
API free tier may use customer submissions for improving Google's services**;
use fictitious/sanitized tickets for testing and review Google's terms before
submitting real customer data. Free quotas and model availability vary.

## Configuration

Configuration is read from environment variables in the backend **process**.
Do not put secrets into the Git repository or frontend JavaScript.

The deployment owner controls the deployed model names, credentials, timeout and
categories. API clients choose only `baseline`, `openai` or `gemini` for each
request. `POST /classify` accepts only `text` and optional `provider`; other fields
return HTTP 400 `unsupported_fields` before any provider call or saved case.
There is no endpoint to edit model settings, API keys or prompts. The provider
catalog does not disclose keys. Successful case metadata includes the model
identifier for traceability; a visible model identifier is not permission to
change it.

The defaults below describe the source code, not a guarantee of the active
production configuration. Deployment environment values override them. Editing
a contributor's local checkout or environment does not change the deployed
service. Access to the deployment configuration remains the owner's responsibility;
this API does not implement deployment administration or contributor login.

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | Default: `baseline`, `openai` or `gemini` | `baseline` |
| `OPENAI_API_KEY` | Server-only OpenAI API key | unset |
| `OPENAI_MODEL` | OpenAI model identifier | `gpt-4.1-mini` |
| `GEMINI_API_KEY` | Server-only Gemini API key | unset |
| `GEMINI_MODEL` | Google AI model identifier | `gemini-3.1-flash-lite` |
| `LLM_TIMEOUT_SECONDS` | Maximum provider request duration (1–20 seconds) | `8` |
| `LLM_CATEGORIES` | Optional comma-separated assertion of the complete Bitext label set | all nine |

The classifier uses `ACCOUNT`, `ORDER`, `INVOICE`, `CONTACT`, `PAYMENT`,
`FEEDBACK`, `REFUND`, `DELIVERY`, and `SHIPPING`. If an environment has an
older category override, remove it or replace it with all nine exact labels.
Existing case records keep their original categories.

For local development without credentials, use the local rules provider or the
offline test suite. Production keys stay in the private deployment environment;
do not copy them into a contributor's checkout. Live cloud calls require
server-side credentials in the environment where the backend is running.

For Gemini, this sends the ticket text to Google's `generateContent` API using a
server-side `x-goog-api-key` header, not a client-side key. The request uses
JSON-only output, a small output limit and temperature zero (this does not guarantee identical results). User
text is treated as untrusted input, not system instructions. Provider errors,
invalid categories, malformed JSON and timeouts follow the explicit-error or
default-fallback behavior described above.
For debugging, logs record the error *type*, not the ticket contents or API key.

## Models and prompts

| Provider | Code default model | Request format | Generation settings |
|---|---|---|---|
| Local rules | No LLM; keyword classifier | Local function | No cloud request or prompt |
| OpenAI | `gpt-4.1-mini` | Chat Completions, system instructions and a separate user message | Temperature 0, 256 maximum completion tokens, JSON object output |
| Gemini | `gemini-3.1-flash-lite` | `generateContent`, system instruction and a separate user message | Temperature 0, 256 maximum output tokens, JSON MIME type |

These model names are implementation defaults, not a claim about free-tier
eligibility, cost or model quality. Selecting a provider uses its server-configured
model; the client cannot supply a model identifier.

Both cloud adapters send the support message separately as a JSON object with a
`ticket` field. Both ask for exactly one allowed category and a numeric confidence
between 0 and 1, and prohibit repeating the customer's text or personal data.
The backend independently validates the returned label and confidence. Confidence
is a model estimate, not calibrated accuracy or a probability of correctness.
Gemini additionally asks for lower confidence on ambiguous tickets.

Both providers load the selected system prompt from
[`backend/llms/prompts.py`](../llms/prompts.py). Runtime classification
uses V1. Evaluation can select V1, V2, or V3 for either provider. All versions
receive the same canonical labels and category guidance from
[`backend/keyword_classifier.py`](../keyword_classifier.py).

## Acceptance tests

Run from the repository root:

```bash
python3 -m unittest discover -s backend/tests -v
```

The test suite uses **mock Gemini and OpenAI responses**, so it requires no network, billing
or credentials. It verifies the API contract, the nine-label set, response
validation, persistence, fallback, provider selection and isolation between
requests. A **live API** end-to-end evaluation is still required to check
classification quality with examples across all nine categories.
Do not claim offline tests demonstrate actual remote model quality.

Each cloud provider’s `confidence` field is model-reported and **not a calibrated
probability**; use Human Review especially for uncertain or consequential cases.
