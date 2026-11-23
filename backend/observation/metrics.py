"""Provider usage and cost metadata shared by manual and automatic recording."""

def safe_response_headers(headers):
    allowed = {"x-request-id", "request-id", "retry-after", "openai-processing-ms"}
    return {k.lower(): v for k, v in (headers.items() if headers else [])
            if k.lower() in allowed or k.lower().startswith("x-ratelimit-")}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _tokens(value, default=None):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default


def request_metrics(provider, model, response, elapsed, transport, config):
    response = _mapping(response)
    usage = response.get("usage", {}) if provider == "openai" else response.get("usageMetadata", {})
    usage = usage if isinstance(usage, dict) else {}
    inp = _tokens(usage.get("prompt_tokens" if provider == "openai" else "promptTokenCount"))
    out = _tokens(usage.get("completion_tokens" if provider == "openai" else "candidatesTokenCount"))
    cached = _mapping(usage.get("prompt_tokens_details")).get("cached_tokens", 0) if provider == "openai" else usage.get("cachedContentTokenCount", 0)
    reasoning = _mapping(usage.get("completion_tokens_details")).get("reasoning_tokens", 0) if provider == "openai" else usage.get("thoughtsTokenCount", 0)
    cached = _tokens(cached, 0)
    reasoning = _tokens(reasoning, 0)
    if inp is not None:
        cached = min(cached, inp)
    billed_output = out + reasoning if provider == "gemini" and out is not None else out
    rates = config.get("pricing", {}).get(model)
    cost = None
    if rates and inp is not None and billed_output is not None:
        cost = (max(0, inp-cached)*rates["input"] + cached*rates["cached_input"] + billed_output*rates["output"])/1_000_000
    return {**transport, "provider": provider, "requested_model": model,
            "returned_model": response.get("model", response.get("modelVersion")),
            "response_id": response.get("id", response.get("responseId")),
            "duration_seconds": round(elapsed, 4), "attempts": 1, "retries": 0,
            "input_tokens": inp, "output_tokens": out, "cached_input_tokens": cached,
            "reasoning_tokens": reasoning, "total_tokens": usage.get("total_tokens", usage.get("totalTokenCount")),
            "estimated_standard_cost_usd": cost, "pricing_snapshot": rates,
            "cost_note": "Schätzung zum Standardtarif, keine Rechnung; Free Tier, Rabatte und Sonderkosten nicht berücksichtigt. Unbekannte Werte bleiben leer.",
            "finish_reasons": [c.get("finish_reason", c.get("finishReason")) for c in (response.get("choices") or response.get("candidates") or []) if isinstance(c, dict)],
            "usage_raw": usage}
