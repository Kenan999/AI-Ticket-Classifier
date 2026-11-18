"""Provider observations; metadata is not an account quota."""
import json
import math
import re
from dataclasses import replace
from time import monotonic
from urllib.request import Request, urlopen
from urllib.error import HTTPError

def model_limits(provider, model, key, configured):
    if provider != "gemini":
        return configured, "configured model limits", 0
    request = Request("https://generativelanguage.googleapis.com/v1beta/models/" + model,
                      headers={"x-goog-api-key": key})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized metadata")
        data = json.loads(raw)
        inp, out = data["inputTokenLimit"], data["outputTokenLimit"]
        if any(type(v) is not int or not 1 <= v <= 10000000 for v in (inp, out)):
            raise ValueError("invalid metadata")
        # Treat the input limit conservatively as a combined context ceiling.
        return replace(configured, context_tokens=min(configured.context_tokens, inp),
                       output_tokens=min(configured.output_tokens, out),
                       input_budget=min(configured.input_budget, inp)), "Gemini live model metadata", 1
    except (OSError, ValueError, KeyError, TypeError):
        return configured, "configured fallback: Gemini metadata unavailable", 1

def duration(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:\d+(?:\.\d+)?(?:ms|s|m|h))+", value):
        return None
    units = {"ms": .001, "s": 1, "m": 60, "h": 3600}
    seconds = sum(float(n)*units[u] for n,u in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)",value))
    return seconds if math.isfinite(seconds) else None

class RateWindow:
    def __init__(self):
        self.values = {}
        self.seen_at = 0
    def observe(self, headers):
        names = ("remaining-requests", "remaining-tokens", "remaining-project-tokens",
                 "reset-requests", "reset-tokens", "reset-project-tokens")
        self.values = {name: headers.get("x-ratelimit-"+name) for name in names
                       if isinstance(headers.get("x-ratelimit-"+name), str)}
        self.seen_at = monotonic()
    def wait_for(self, token_bound):
        waits = [0.0]
        for resource, needed in (("requests",1),("tokens",token_bound),("project-tokens",token_bound)):
            remaining = self.values.get("remaining-"+resource, "")
            if remaining.isdecimal() and int(remaining) < needed:
                delay = duration(self.values.get("reset-"+resource))
                if delay is not None:
                    waits.append(max(0, self.seen_at + delay - monotonic()) + .25)
        return max(waits)
