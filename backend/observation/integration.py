"""Composition hooks for Flask and AI Operations; no Evaluation file changes."""
from functools import wraps
from threading import Lock

from .tracing import annotate_run, observed_call, run_scope

_install_lock = Lock()


def install_flask(app):
    from flask import g, request

    @app.before_request
    def begin_observation():
        if request.endpoint == "classify" and request.method == "POST":
            from backend.llms.prompts import DEFAULT_PROMPT_VERSION
            scope = run_scope("application", run_kind="single", prompt_version=DEFAULT_PROMPT_VERSION)
            g.observation_scope = scope
            g.observation_state = scope.__enter__()

    @app.after_request
    def link_observation(response):
        state = getattr(g, "observation_state", None)
        if state:
            data = response.get_json(silent=True) or {}
            annotate_run(state, ticket_id=data.get("ticket_id"),
                         application_status=response.status_code,
                         fallback_used=data.get("fallback_used", False))
        return response

    @app.teardown_request
    def end_observation(error):
        scope = g.pop("observation_scope", None)
        if scope:
            scope.__exit__(None, None, None)


def install_evaluation():
    """Install once before the dashboard imports the evaluation runner.

    Kept at the AI Operations entry point so the Evaluation package stays
    unchanged. Direct CLI users can call this before importing the runner.
    ContextVars keep simultaneous sessions and application requests separate.
    """
    from backend.evaluation import batching, evaluate
    with _install_lock:
        if not getattr(batching.request_batch, "_observation_wrapped", False):
            batching.request_batch = observed_call(batching.request_batch)
        if getattr(evaluate.run_evaluation, "_observation_wrapped", False):
            return
        original = evaluate.run_evaluation

        @wraps(original)
        def run(tickets, provider=evaluate.BASELINE, *, batch=False, progress=None):
            method = evaluate.PROVIDERS.get(provider, {})
            with run_scope("evaluation", method=provider,
                           prompt_version=method.get("prompt_version"),
                           run_kind="loop" if len(tickets) > 1 else "single",
                           ticket_count=len(tickets), batch=batch) as state:
                if state:
                    state["ticket_ids"] = [ticket.get("ticket_id") for ticket in tickets]
                return original(tickets, provider=provider, batch=batch, progress=progress)
        run._observation_wrapped = True
        evaluate.run_evaluation = run
