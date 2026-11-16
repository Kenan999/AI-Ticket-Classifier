"""Optional OpenAI ticket classification adapter. Keys stay server-side."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from .classifier import PredictionResult
    from .llm_classifier import LLMError, configured_categories
except ImportError:
    from classifier import PredictionResult
    from llm_classifier import LLMError, configured_categories

from evaluation.prompts import DEFAULT_PROMPT_VERSION, render_prompt

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
MAX_RESPONSE_BYTES = 32 * 1024


def classify_with_openai(text, *, api_key, categories, model=DEFAULT_OPENAI_MODEL,
                         timeout=8.0, opener=None, prompt_version=DEFAULT_PROMPT_VERSION):
    if not api_key or not api_key.strip():
        raise LLMError("OPENAI_API_KEY is not configured")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model):
        raise LLMError("Invalid OpenAI model name")
    if not 1 <= float(timeout) <= 20:
        raise LLMError("LLM timeout must be 1–20 seconds")
    categories = configured_categories(",".join(categories))
    instructions = render_prompt(prompt_version, "openai", categories)
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
        with (opener or urlopen)(request, timeout=float(timeout)) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
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
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError,
            TypeError, IndexError, UnicodeDecodeError) as exc:
        raise LLMError("OpenAI request or response failed") from exc
