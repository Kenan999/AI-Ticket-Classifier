"""Shared, credential-free model registry for all LLM providers."""
import json
import os
from pathlib import Path


def model_configuration(environment=None):
    """Load model metadata and apply optional environment model overrides."""
    env = os.environ if environment is None else environment
    config = json.loads((Path(__file__).with_name("models.json")).read_text())
    for item in config["llms"]:
        override = env.get(item["model_environment_variable"], "").strip()
        item["model"] = override or item["default_model"]
    return config


def default_model(provider):
    return next(item["default_model"] for item in model_configuration({})["llms"]
                if item["id"] == provider)
