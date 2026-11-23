"""Local LLM endpoint and model configuration."""
import os
from ..registry import default_model

DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:18642/v1/chat/completions"

def configured_model():
    return os.environ.get("LOCAL_LLM_MODEL", "").strip() or default_model("local")

def configured_endpoint():
    return os.environ.get("LOCAL_LLM_ENDPOINT", "").strip() or DEFAULT_LOCAL_ENDPOINT
