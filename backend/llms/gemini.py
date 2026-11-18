"""Optional Gemini REST adapter for a user-configurable set of support categories.

The API key stays on the backend. Customer text is sent to Gemini ONLY when
Gemini is selected by the request or server default and a server key is configured. No network calls at import.
"""
import json
import os
import re
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.classifier import CATEGORY_GUIDANCE, DATASET_CATEGORIES, PredictionResult
from .retry import LLMError, read_provider_response
from .prompts import DEFAULT_PROMPT_VERSION, render_prompt

DEFAULT_CATEGORIES = DATASET_CATEGORIES
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_RESPONSE_BYTES = 32 * 1024


def configured_categories(raw=None):
    """Use exactly the nine dataset labels; reject stale deployment overrides."""
    if raw is None:
        raw = os.getenv("LLM_CATEGORIES", "")
    if not isinstance(raw, str):
        raise ValueError("LLM_CATEGORIES must be a string")
    if not raw.strip():
        return DEFAULT_CATEGORIES
    values = tuple(item.strip() for item in raw.split(","))
    if (len(values) != len(DEFAULT_CATEGORIES)
            or len(set(values)) != len(DEFAULT_CATEGORIES)
            or set(values) != set(DEFAULT_CATEGORIES)):
        raise ValueError("LLM_CATEGORIES must contain exactly the nine Bitext labels")
    return DEFAULT_CATEGORIES


def classify_with_gemini(text, *, api_key, categories, model=DEFAULT_MODEL,
                         timeout=8.0, opener=None, prompt_version=DEFAULT_PROMPT_VERSION,
                         instructions=None, retry_budget=None):
    """Return a validated classification; raise LLMError for any bad response.

    Callers can supply a rendered system prompt through instructions.
    Otherwise, render the requested version from the shared registry.
    The confidence is a *model-reported estimate*, NOT a calibrated probability.
    """
    if not api_key or not api_key.strip():
        raise LLMError("GEMINI_API_KEY is not configured")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model):
        raise LLMError("Invalid Gemini model name")
    if not 1 <= float(timeout) <= 20:
        raise LLMError("LLM timeout must be 1–20 seconds")
    categories = configured_categories(",".join(categories))
    if instructions is None:
        instructions = render_prompt(
            prompt_version, "gemini", categories, category_guidance=CATEGORY_GUIDANCE,
        )
    elif not isinstance(instructions, str) or not instructions.strip():
        raise LLMError("Gemini instructions must be a non-empty string")
    payload = {
        "systemInstruction": {"parts": [{"text": instructions}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps({"ticket": text})}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
        },
    }
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + quote(model, safe="._-") + ":generateContent"
    )
    req = Request(
        endpoint, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        body = read_provider_response(
            req, opener=urlopen if opener is None else opener,
            timeout=float(timeout), retry_budget=retry_budget, max_bytes=MAX_RESPONSE_BYTES, provider="Gemini",
        )
        if len(body) > MAX_RESPONSE_BYTES:
            raise LLMError("Provider response exceeded size limit")
        data = json.loads(body)
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise LLMError("Provider did not return a classification")
        parts = candidates[0]["content"]["parts"]
        result = json.loads("".join(part["text"] for part in parts))
        if not isinstance(result, dict):
            raise LLMError("Classification response must be an object")
        category = result.get("category")
        confidence = result.get("confidence")
        if category not in categories:
            raise LLMError("Provider returned an unknown category")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1):
            raise LLMError("Provider returned an invalid confidence")
        return PredictionResult(category, float(confidence), "gemini:" + model)
    except (URLError, TimeoutError, OSError, ValueError, KeyError,
            TypeError, IndexError, UnicodeDecodeError) as exc:
        # Do not include response bodies, requests, API keys or customer text in logs.
        raise LLMError("Gemini request or response failed") from exc
