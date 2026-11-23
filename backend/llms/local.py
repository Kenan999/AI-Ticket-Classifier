"""Shoply-local Qwen ticket classifier; no cloud credentials required."""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError
from backend.keyword_classifier import PredictionResult, CATEGORY_GUIDANCE
from .prompts import render_prompt, DEFAULT_PROMPT_VERSION
from .retry import LLMError
from .gemini import configured_categories
from backend.observation import store
from pathlib import Path
from uuid import uuid4

DEFAULT_LOCAL_MODEL = 'mlx-community/Qwen3-4B-Instruct-2507-4bit'
DEFAULT_LOCAL_ENDPOINT = 'http://127.0.0.1:18642/v1/chat/completions'


def classify_with_local(text, *, categories, model=DEFAULT_LOCAL_MODEL, timeout=30, endpoint=None, observation_source="application", prompt_version=DEFAULT_PROMPT_VERSION, **_):
    categories = configured_categories(','.join(categories))
    endpoint = endpoint or os.getenv('LOCAL_LLM_ENDPOINT', DEFAULT_LOCAL_ENDPOINT)
    if not endpoint.startswith(('http://127.0.0.1:', 'http://localhost:')):
        raise LLMError('Local model endpoint must be loopback')
    instruction = render_prompt(prompt_version, "local", categories, category_guidance=CATEGORY_GUIDANCE)
    instruction += "\nConfidence must be a JSON number between 0 and 1, never a word. "
    instruction += "ORDER includes checking where an existing order is, its status and tracking; DELIVERY covers general delivery methods and timeframes."
    payload = {'model': model, 'messages': [
        {'role': 'system', 'content': instruction},
        {'role': 'user', 'content': json.dumps({'ticket': text})}], 'stream': False, 'max_tokens': 256}
    observation = None
    ident = uuid4().hex
    try:
        config = json.loads((Path(__file__).resolve().parents[1] / 'observation' / 'config.json').read_text())
        if config.get('recording', {}).get('enabled'):
            store.start(config, ident=ident, source=observation_source, provider='local', model=model,
                        request={'ticket': text}, run_id=None, created_at=store.timestamp())
            observation = config
    except Exception:
        pass
    req = Request(endpoint, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=float(timeout)) as response:
            result = json.load(response)
        raw = result['choices'][0]['message']['content'].strip().replace('<|im_end|>', '').strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        data = json.loads(raw)
        category, confidence = data['category'], data['confidence']
        if category not in categories or isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not 0 <= confidence <= 1:
            raise ValueError('Invalid classification')
        if observation:
            try: store.finish(observation, ident, {'category': category, 'confidence': confidence, 'usage': result.get('usage', {})}, None, store.timestamp())
            except Exception: pass
        return PredictionResult(category, float(confidence), 'local:' + model)
    except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        if observation:
            try: store.finish(observation, ident, None, {'type': type(exc).__name__}, store.timestamp())
            except Exception: pass
        raise LLMError('Local classification failed') from exc
