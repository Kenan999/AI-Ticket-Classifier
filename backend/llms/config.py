"""Deployment supplies secrets through the backend process environment."""
import os


def openai_api_key():
    """Return the deployment-provided key without reading a local secret file."""
    return os.environ.get("OPENAI_API_KEY", "").strip()
