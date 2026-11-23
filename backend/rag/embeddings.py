"""Provider-specific embedding adapters behind a shared RAG interface.

Embeddings from different models are never comparable. Local requires a
separate embedding-serving endpoint, not the Qwen chat-completion endpoint.
"""
import json
import os
from urllib.request import Request, urlopen

GEMINI_MODEL = 'gemini-embedding-001'
OPENAI_MODEL = 'text-embedding-3-small'
LOCAL_MODEL = 'local-embedding-model'


def model_name(provider):
    defaults = {'gemini': GEMINI_MODEL, 'openai': OPENAI_MODEL, 'local': LOCAL_MODEL}
    variables = {'gemini': 'GEMINI_EMBEDDING_MODEL', 'openai': 'OPENAI_EMBEDDING_MODEL', 'local': 'LOCAL_EMBEDDING_MODEL'}
    if provider not in defaults:
        raise ValueError('Unsupported embedding provider')
    return os.getenv(variables[provider], '').strip() or defaults[provider]


def embed(text, task_type, provider='gemini', *, credentials=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Embedding text must be nonempty')
    credentials = credentials or {}
    model = model_name(provider)
    if provider == 'gemini':
        key = os.getenv('GEMINI_API_KEY') or credentials.get('GEMINI_API_KEY')
        if not key:
            raise RuntimeError('Gemini embedding key is unavailable')
        payload = {'model': 'models/' + model, 'content': {'parts': [{'text': text}]}, 'taskType': task_type}
        url = 'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':embedContent'
        headers = {'Content-Type': 'application/json', 'x-goog-api-key': key}
    elif provider == 'openai':
        key = os.getenv('OPENAI_API_KEY') or credentials.get('OPENAI_API_KEY')
        if not key:
            raise RuntimeError('OpenAI embedding key is unavailable')
        payload = {'model': model, 'input': text}
        url = 'https://api.openai.com/v1/embeddings'
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}
    elif provider == 'local':
        url = os.getenv('LOCAL_EMBEDDING_ENDPOINT', 'http://127.0.0.1:18643/v1/embeddings')
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        if parts.scheme != 'http' or parts.hostname not in ('localhost', '127.0.0.1') or not parts.port or parts.username or parts.password or parts.query or parts.fragment or parts.path != '/v1/embeddings':
            raise ValueError('Local embedding endpoint must be a loopback /v1/embeddings URL')
        payload = {'model': model, 'input': text}
        headers = {'Content-Type': 'application/json'}
    else:
        raise ValueError('Unsupported embedding provider')
    request = Request(url, data=json.dumps(payload).encode('utf-8'), method='POST', headers=headers)
    with urlopen(request, timeout=25) as response:
        result = json.load(response)
    vector = result['embedding']['values'] if provider == 'gemini' else result['data'][0]['embedding']
    if not isinstance(vector, list) or not vector or any(not isinstance(v, (float, int)) or isinstance(v, bool) for v in vector):
        raise ValueError('Invalid embedding vector')
    return vector
