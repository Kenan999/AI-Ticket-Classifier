"""OpenAI-specific environment configuration; no secret files."""
import os
from ..registry import default_model


def openai_api_key():
    return os.environ.get("OPENAI_API_KEY", "").strip()


def configured_model():
    return os.environ.get("OPENAI_MODEL", "").strip() or default_model("openai")
