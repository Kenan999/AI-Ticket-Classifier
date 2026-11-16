# Optional LLM-based Ticket Classification (IHK-028)

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

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | Default: `baseline`, `openai` or `gemini` | `baseline` |
| `OPENAI_API_KEY` | Server-only OpenAI API key | unset |
| `OPENAI_MODEL` | OpenAI model identifier | `gpt-4.1-mini` |
| `GEMINI_API_KEY` | Server-only Gemini API key | unset |
| `GEMINI_MODEL` | Google AI model identifier | `gemini-3.1-flash-lite` |
| `LLM_TIMEOUT_SECONDS` | Maximum provider request duration (1–20 seconds) | `8` |
| `LLM_CATEGORIES` | Comma-separated exact category labels | existing seven |

At this stage the default labels stay unchanged: `Returns`, `Shipping`,
`Billing`, `Account`, `Technical`, `Orders`, `General`. The ticket IHK-028
suggests `Delivery`, `Refund`, `Payment`, `Order`, `Account`. **Do not change
labels until the frontend, Human Review workflow, customer-reply templates,
existing cases, and the agreed acceptance criteria are updated together.**

Example (run locally with fictional tickets and a key supplied securely):

```bash
export LLM_PROVIDER=gemini
export GEMINI_API_KEY='your-private-key-from-Google-AI-Studio'
export GEMINI_MODEL=gemini-3.1-flash-lite
python3 backend/app.py
```

For Gemini, this sends the ticket text to Google's `generateContent` API using a
server-side `x-goog-api-key` header, not a client-side key. The request uses
JSON-only output, a small output limit and deterministic temperature. User
text is treated as untrusted input, not system instructions. Provider errors,
invalid categories, malformed JSON and timeouts follow the explicit-error or
default-fallback behavior described above.
For debugging, logs record the error *type*, not the ticket contents or API key.

## Acceptance tests

Run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The test suite uses **mock Gemini and OpenAI responses**, so it requires no network, billing
or credentials. It verifies the API contract, custom categories, response
validation, persistence, fallback, provider selection and isolation between
requests. A **live API** end-to-end evaluation is still required to check
classification quality with fictional examples across all seven app categories.
Do not claim offline tests demonstrate actual remote model quality.

The Gemini `confidence` field is model-reported and **not a calibrated
probability**; use Human Review especially for uncertain or consequential cases.
