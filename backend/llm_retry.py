"""Bounded retries for the Gemini and OpenAI HTTP adapters."""

from email.utils import parsedate_to_datetime
from http.client import HTTPException
import json
from random import uniform
from time import monotonic, sleep, time
from urllib.error import HTTPError


RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
QUOTA_ERRORS = {"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached"}
MAX_RETRIES = 2
MAX_ERROR_BYTES = 8192


class LLMError(Exception):
    """Provider unavailable, invalid configuration or untrusted response."""


def _header_delay(headers):
    if not headers:
        return 0.0
    value = headers.get("Retry-After", "").strip()
    if value.isascii() and value.isdecimal():
        return float(value)
    if value:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is not None:
                return max(0.0, retry_at.timestamp() - time())
        except (TypeError, ValueError, OverflowError):
            pass
    milliseconds = headers.get("Retry-After-Ms", "").strip()
    return float(milliseconds) / 1000 if milliseconds.isascii() and milliseconds.isdecimal() else 0.0


def _rate_limit_details(response):
    """Read only structured quota codes and Google RetryInfo from a 429."""
    try:
        payload = json.loads(response.read(MAX_ERROR_BYTES))
    except (HTTPException, OSError, ValueError, RecursionError):
        return False, 0.0
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return False, 0.0
    codes = (error.get("code"), error.get("type"))
    if any(isinstance(code, str) and code in QUOTA_ERRORS for code in codes):
        return True, 0.0
    details = error.get("details")
    delays = []
    for detail in details if isinstance(details, list) else []:
        if (not isinstance(detail, dict)
                or detail.get("@type") != "type.googleapis.com/google.rpc.RetryInfo"):
            continue
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                delays.append(float(delay[:-1]))
            except ValueError:
                continue
    return False, max([0.0, *delays])


def read_provider_response(request, *, opener, timeout, max_bytes, provider):
    """Read the response, using the original timeout as the retry budget."""
    deadline = monotonic() + timeout
    remaining = timeout
    for attempt in range(MAX_RETRIES + 1):
        try:
            with opener(request, timeout=remaining) as response:
                return response.read(max_bytes + 1)
        except HTTPError as error:
            status = error.code
            with error:
                if status not in RETRYABLE_STATUSES:
                    raise LLMError(f"{provider} request failed (HTTP {status})") from error
                delay = _header_delay(error.headers)
                if status == 429:
                    quota_exhausted, retry_info = _rate_limit_details(error)
                    if quota_exhausted:
                        raise LLMError(f"{provider} quota exhausted (HTTP 429)") from error
                    delay = max(delay, retry_info)

            failure = (f"{provider} rate limit (HTTP 429)" if status == 429
                       else f"{provider} temporary error (HTTP {status})")
            if attempt == MAX_RETRIES:
                raise LLMError(f"{failure}; retries exhausted") from error
            backoff = 0.5 * 2 ** attempt
            wait = max(delay, backoff + uniform(0, backoff / 2))
            if wait >= deadline - monotonic():
                raise LLMError(f"{failure}; retry wait exceeds timeout") from error
            sleep(wait)
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise LLMError(f"{failure}; retry wait exceeds timeout") from error
