"""Local demo setting for the customer-facing AI chat provider."""
import json
from pathlib import Path
from threading import Lock

PATH=Path(__file__).resolve().parents[2]/'results'/'chat_provider.json'
LOCK=Lock()
ALLOWED=('gemini','openai','local')

def get():
    with LOCK:
        try:
            value=json.loads(PATH.read_text()).get('provider','gemini')
            return value if value in ALLOWED else 'gemini'
        except (OSError,ValueError,AttributeError):return 'gemini'

def set_provider(value):
    if value not in ALLOWED:raise ValueError('Choose Gemini, OpenAI or Local Qwen')
    with LOCK:
        PATH.parent.mkdir(parents=True,exist_ok=True)
        tmp=PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps({'provider':value}))
        tmp.replace(PATH)
    return {'provider':value}
