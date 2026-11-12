# Optional LLM-based Ticket Classification (IHK-028)

This integration is part of the **Backend development branch**, not the live
website. It does not add another Flask endpoint: the frontend continues to call
`POST /classify` with `{"text":"..."}` and receives the same response fields.

## How it works

1. Frontend sends a ticket to `POST /classify`.
2. Backend validates the text and sends it to the Google Gemini Developer API
   only if `LLM_PROVIDER=gemini` **and** `GEMINI_API_KEY` is present.
3. Gemini receives an English classification prompt, the customer text and the
   currently configured allowed category names; its JSON response must select
   exactly one label and provide a numeric confidence estimate (0–1).
4. Backend validates the response, stores the ticket in SQLite and returns its
   category, status and metadata to the frontend. Low-confidence predictions
   go to Human Review. A human must confirm any customer-facing reply.
5. If the provider is disabled or unavailable, the existing keyword classifier
   handles the ticket instead; `model_version` shows which classifier was used.

No ticket data is sent to Gemini unless it is explicitly enabled. **The Gemini
API free tier may use customer submissions for improving Google's services**;
use fictitious/sanitized tickets for testing and review Google's terms before
submitting real customer data. Free quotas and model availability vary.

## Configuration

Configuration is read from environment variables in the backend **process**.
Do not put secrets into the Git repository or frontend JavaScript.

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | `baseline` or `gemini` | `baseline` |
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

This sends the ticket text to Google's `generateContent` API using a
server-side `x-goog-api-key` header, not a client-side key. The request uses
JSON-only output, a small output limit and deterministic temperature. User
text is treated as untrusted input, not system instructions. Provider errors,
invalid categories, malformed JSON and timeouts fall back to the baseline.
For debugging, logs record the error *type*, not the ticket contents or API key.

## Acceptance tests

Run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The test suite uses **mock Gemini responses**, so it requires no network, billing
or credentials. It verifies the API contract, custom categories, response
validation, persistence, fallback and five example classifications (one per
proposed MVP category). A **live Gemini API** end-to-end evaluation is still
required after a key is configured and consent for sample inputs is confirmed.
Do not claim offline tests demonstrate actual remote model quality.

The Gemini `confidence` field is model-reported and **not a calibrated
probability**; use Human Review especially for uncertain or consequential cases.
