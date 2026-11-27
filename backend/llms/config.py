"""Deployment supplies secrets through the backend process environment."""
import os


def openai_api_key():
    """Return the deployment-provided key without reading a local secret file."""
    return os.environ.get("OPENAI_API_KEY", "").strip()


# Public model metadata only; credentials never enter this object.
def model_configuration(environment=None):
    """Return a fresh JSON-compatible registry with effective model names.

    Explicit environment mappings let application, evaluation and external
    consumers use the same settings without sharing credentials.
    """
    import json
    from pathlib import Path
    env = os.environ if environment is None else environment
    config = json.loads(Path(__file__).with_name("models.json").read_text())
    for item in config["llms"]:
        override = env.get(item["model_environment_variable"], "").strip()
        item["model"] = override or item["default_model"]
    return config


def default_model(provider):
    return next(item["default_model"] for item in model_configuration({})["llms"]
                if item["id"] == provider)
