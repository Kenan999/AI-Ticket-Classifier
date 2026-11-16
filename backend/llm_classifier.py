"""Optional Gemini REST adapter for a user-configurable set of support categories.

The API key stays on the backend. Customer text is sent to Gemini ONLY when
Gemini is selected by the request or server default and a server key is configured. No network calls at import.
"""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from .classifier import CATEGORY_GUIDANCE, DATASET_CATEGORIES, PredictionResult
except ImportError:  # direct execution: python3 backend/app.py
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from classifier import CATEGORY_GUIDANCE, DATASET_CATEGORIES, PredictionResult

from evaluation.prompts import DEFAULT_PROMPT_VERSION, render_prompt

DEFAULT_CATEGORIES = DATASET_CATEGORIES
DEFAULT_MODEL = "gemini-3.1-flash-lite"
MAX_RESPONSE_BYTES = 32 * 1024


class LLMError(Exception):
    """Provider unavailable, invalid configuration or untrusted response."""


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
                         timeout=8.0, opener=None, prompt_version=DEFAULT_PROMPT_VERSION):
    """Return a validated classification; raise LLMError for any bad response.

    The confidence is a *model-reported estimate*, NOT a calibrated probability.
    """
    if not api_key or not api_key.strip():
        raise LLMError("GEMINI_API_KEY is not configured")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model):
        raise LLMError("Invalid Gemini model name")
    if not 1 <= float(timeout) <= 20:
        raise LLMError("LLM timeout must be 1–20 seconds")
    categories = configured_categories(",".join(categories))
    instructions = render_prompt(
        prompt_version, "gemini", categories, category_guidance=CATEGORY_GUIDANCE,
    )
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
    open_request = opener if opener is not None else urlopen
    try:
        with open_request(req, timeout=float(timeout)) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
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
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError,
            TypeError, IndexError, UnicodeDecodeError) as exc:
        # Do not include response bodies, requests, API keys or customer text in logs.
        raise LLMError("Gemini request or response failed") from exc
