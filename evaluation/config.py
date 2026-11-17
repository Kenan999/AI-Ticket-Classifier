"""Shared evaluation batching policy. No credentials belong here."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelLimits:
    context_tokens: int
    output_tokens: int
    max_tickets: int | None = None
    input_budget: int = 16000
    answer_tokens_per_ticket: int = 128
    reserve_tokens: int = 2048

# Official model documentation, checked November 2026:
# https://developers.openai.com/api/docs/models/gpt-4.1-mini
# https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite
MODEL_LIMITS = {
    ("openai", "gpt-4.1-mini"): ModelLimits(1047576, 32768),
    ("gemini", "gemini-3.1-flash-lite"): ModelLimits(1048576, 65536),
}

# Evaluation may wait longer than interactive application requests.
RETRY_BUDGET_SECONDS = 300
REQUEST_INTERVAL_SECONDS = 6

# Multi-ticket generation can take longer than an interactive single ticket.
BATCH_REQUEST_TIMEOUT_SECONDS = 60
