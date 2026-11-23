"""Read-only provider connectivity checks for the local Settings dashboard."""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from backend.chat.service import settings


def _check(url, headers=None):
    try:
        with urlopen(Request(url, headers=headers or {}), timeout=4) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def statuses():
    config = settings()
    def credential(name):
        return (os.getenv(name) or config.get(name) or '').strip()
    openai = credential('OPENAI_API_KEY')
    gemini = credential('GEMINI_API_KEY')
    local_url = credential('LOCAL_LLM_ENDPOINT') or 'http://127.0.0.1:18642/v1/chat/completions'
    # Only contact loopback for local inference; never use an arbitrary configured URL.
    from urllib.parse import urlsplit
    parsed = urlsplit(local_url)
    local_safe = parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1') and parsed.port is not None
    local_base = f'http://{parsed.hostname}:{parsed.port}' if local_safe else None
    checks = [
        ('openai', 'OpenAI', bool(openai), _check('https://api.openai.com/v1/models', {'Authorization': 'Bearer ' + openai}) if openai else False),
        ('gemini', 'Gemini', bool(gemini), _check('https://generativelanguage.googleapis.com/v1beta/models', {'x-goog-api-key': gemini}) if gemini else False),
        ('local', 'Local Qwen3-4B', local_safe, _check(local_base + '/v1/models') if local_base else False),
    ]
    return {'providers': [{'id': ident, 'label': label, 'status': 'connected' if connected else ('disconnected' if configured else 'not_configured')} for ident,label,configured,connected in checks]}
