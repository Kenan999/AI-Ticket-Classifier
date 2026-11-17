"""Shared evaluation batching policy. No credentials belong here."""
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelLimits:
    context_tokens: int
    output_tokens: int
    max_tickets: int = 20
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
