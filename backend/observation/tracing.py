"""Opt-in recording scopes; storage failures never alter provider results."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
import logging
import os
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit, unquote
from uuid import uuid4

from .database import DEFAULT_CONFIG
from .metrics import request_metrics, safe_response_headers
from . import store

_run = ContextVar("observation_run", default=None)
_call = ContextVar("observation_call", default=None)
logger = logging.getLogger(__name__)


def best_effort(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        # Exception messages can include ticket text, paths or credentials.
        logger.warning("Observation recording skipped (%s)", type(exc).__name__)
        return None


def _configuration(source):
    config = json.loads(Path(os.environ.get("OBSERVATION_CONFIG", DEFAULT_CONFIG)).read_text())
    recording = config.get("recording", {})
    if recording.get("enabled") is True and source in recording.get("sources", []):
        return config
    return None


@contextmanager
def run_scope(source, **metadata):
    config = best_effort(_configuration, source)
    state = ({"id": uuid4().hex, "source": source, "config": config,
              "metadata": metadata, "recorded": False} if config else None)
    token = _run.set(state)
    try:
        yield state
    finally:
        _run.reset(token)


def annotate_run(state, **metadata):
    if state and state["recorded"]:
        best_effort(store.annotate_run, state["config"], state["id"], metadata)


def observed_call(function):
    """Finish successful transport only after the adapter validates its output."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _run.get() is None:
            return function(*args, **kwargs)
        call = {"id": uuid4().hex, "pending": None,
                "prompt_version": kwargs.get("prompt_version"),
                "batch_size": len(args[0]) if function.__name__ == "request_batch" and args else None}
        state = _run.get()
        index = state.get("call_count", 0)
        state["call_count"] = index + 1
        ids = state.get("ticket_ids", [])
        if function.__name__ == "request_batch" and args:
            indices = [int(item["id"]) for item in args[0] if str(item.get("id", "")).isdigit()]
            call["ticket_ids"] = [ids[i] for i in indices if i < len(ids)]
        else:
            call["ticket_ids"] = ids[index:index + 1]
        token = _call.set(call)
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            if call["pending"]:
                best_effort(call["pending"].finish, exc)
            raise
        else:
            if call["pending"]:
                best_effort(call["pending"].finish)
            return result
        finally:
            _call.reset(token)
    wrapped._observation_wrapped = True
    return wrapped


def _decode(body):
    try:
        return json.loads(body)
    except (ValueError, UnicodeError):
        return {"text": body.decode("utf-8", errors="replace")}


def _bounded(value, config, secrets):
    value = store.clean(value, secrets)
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    limit = min(1024 * 1024, max(1024, int(config["recording"].get("max_content_bytes", 65536))))
    if len(raw) <= limit:
        return value if isinstance(value, dict) else {"body": value}
    return {"truncated": True, "original_bytes": len(raw),
            "preview": raw[:limit].decode("utf-8", errors="ignore")}


class Attempt:
    def __init__(self, request, provider, number, timeout):
        self.run = _run.get()
        self.call = _call.get()
        self.config = self.run["config"]
        self.provider = provider.lower()
        self.ident = uuid4().hex
        self.number = number
        self.started = perf_counter()
        self.done = False
        self.body = None
        self.transport = {}
        self.secrets = []
        for key, value in request.header_items():
            if key.lower() in {"authorization", "x-goog-api-key"}:
                self.secrets.append(value.removeprefix("Bearer "))
        body = request.data or b"{}"
        payload = _decode(body)
        parts = urlsplit(request.full_url)
        endpoint = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        self.model = (payload.get("model") if self.provider == "openai" else
                      unquote(parts.path.rsplit("/models/", 1)[-1].split(":")[0]))
        if not isinstance(self.model, str):
            self.model = "unknown"
        prompt = (payload.get("messages", [{}])[0].get("content", "")
                  if self.provider == "openai" else payload.get("systemInstruction", {}))
        metadata = {**self.run["metadata"], "call_id": self.call["id"] if self.call else self.ident,
                    "attempt_number": number, "retry": number > 1,
                    "endpoint": endpoint, "method": request.get_method(),
                    "timeout_seconds": timeout, "request_bytes": len(body),
                    "prompt_sha256": hashlib.sha256(json.dumps(prompt, sort_keys=True).encode()).hexdigest()}
        if self.call:
            if self.call["prompt_version"]:
                metadata["prompt_version"] = self.call["prompt_version"]
            if self.call["ticket_ids"]:
                metadata["ticket_ids"] = self.call["ticket_ids"]
            if self.call["batch_size"] is not None:
                metadata["batch_size"] = self.call["batch_size"]
        captured = _bounded(payload, self.config, self.secrets)
        captured["_observation"] = metadata
        store.start(self.config, ident=self.ident, source=self.run["source"],
                    provider=self.provider, model=self.model, request=captured,
                    run_id=self.run["id"], created_at=store.timestamp())
        self.run["recorded"] = True

    def received(self, body, status=None, headers=None, error=None):
        self.body = body
        self.transport = {"http_status": status, "response_bytes": len(body),
                          "response_headers": safe_response_headers(headers)}
        self.elapsed = perf_counter() - self.started
        if error is not None or self.call is None:
            self.finish(error)
        else:
            self.call["pending"] = self

    def finish(self, error=None):
        if self.done:
            return
        response = _decode(self.body) if self.body is not None else {}
        elapsed = getattr(self, "elapsed", perf_counter() - self.started)
        metrics = best_effort(request_metrics, self.provider, self.model,
                              response if isinstance(response, dict) else {},
                              elapsed, self.transport, self.config)
        if metrics is None:
            metrics = {**self.transport, "duration_seconds": round(elapsed, 4),
                       "estimated_standard_cost_usd": None, "usage_unavailable": True}
        metrics.update(attempt_number=self.number, retries=int(self.number > 1))
        captured = _bounded(response, self.config, self.secrets) if self.body is not None else None
        if captured is not None:
            captured["_observation"] = metrics
        failure = ({"type": type(error).__name__, "message": store.clean(str(error), self.secrets),
                    "_observation": metrics} if error is not None else None)
        store.finish(self.config, self.ident, captured, failure, store.timestamp())
        self.done = True


def begin_attempt(request, provider, number, timeout):
    if _run.get() is None:
        return None
    return best_effort(Attempt, request, provider, number, timeout)


def received(attempt, body, status=None, headers=None, error=None):
    if attempt is not None:
        best_effort(attempt.received, body, status, headers, error)


def failed(attempt, error):
    if attempt is not None:
        best_effort(attempt.finish, error)
