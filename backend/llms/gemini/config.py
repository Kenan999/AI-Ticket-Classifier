"""Gemini-specific environment configuration."""
import os
from ..registry import default_model


def gemini_api_key():
    return os.environ.get("GEMINI_API_KEY", "").strip()


def configured_model():
    return os.environ.get("GEMINI_MODEL", "").strip() or default_model("gemini")
