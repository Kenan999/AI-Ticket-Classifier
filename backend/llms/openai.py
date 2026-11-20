"""Optional OpenAI ticket classification adapter. Keys stay server-side."""
import json
import re
from urllib.error import URLError
from urllib.request import Request, urlopen

from backend.keyword_classifier import CATEGORY_GUIDANCE, PredictionResult
from .gemini import configured_categories
from .retry import LLMError, read_provider_response
from backend.observation.tracing import observed_call
from .prompts import DEFAULT_PROMPT_VERSION, render_prompt

from .config import default_model

DEFAULT_OPENAI_MODEL = default_model("openai")
MAX_RESPONSE_BYTES = 32 * 1024


@observed_call
def classify_with_openai(text, *, api_key, categories, model=DEFAULT_OPENAI_MODEL,
                         timeout=8.0, opener=None, prompt_version=DEFAULT_PROMPT_VERSION, retry_budget=None):
    if not api_key or not api_key.strip():
        raise LLMError("OPENAI_API_KEY is not configured")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model):
        raise LLMError("Invalid OpenAI model name")
    if not 1 <= float(timeout) <= 20:
        raise LLMError("LLM timeout must be 1–20 seconds")
    categories = configured_categories(",".join(categories))
    instructions = render_prompt(
        prompt_version, "openai", categories, category_guidance=CATEGORY_GUIDANCE,
    )
    payload = {
        "model": model,
        "temperature": 0,
        "max_completion_tokens": 256,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps({"ticket": text})},
        ],
    }
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
        method="POST",
    )
    try:
        body = read_provider_response(
            request, opener=urlopen if opener is None else opener,
            timeout=float(timeout), retry_budget=retry_budget, max_bytes=MAX_RESPONSE_BYTES, provider="OpenAI",
        )
        if len(body) > MAX_RESPONSE_BYTES:
            raise LLMError("Provider response exceeded size limit")
        data = json.loads(body)
        result = json.loads(data["choices"][0]["message"]["content"])
        if not isinstance(result, dict):
            raise LLMError("Classification response must be an object")
        category, confidence = result.get("category"), result.get("confidence")
        if category not in categories:
            raise LLMError("Provider returned an unknown category")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1):
            raise LLMError("Provider returned invalid confidence")
        return PredictionResult(category, float(confidence), "openai:" + model)
    except (URLError, TimeoutError, OSError, ValueError, KeyError,
            TypeError, IndexError, UnicodeDecodeError) as exc:
        raise LLMError("OpenAI request or response failed") from exc
