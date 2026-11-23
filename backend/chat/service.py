"""Customer chat sessions, Gemini replies, and Observation events (separate from classification)."""
import json
import os
import re
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4
from backend.observation import store
from backend.chat import provider as chat_provider
from backend.rag.chat_context import policy_context

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'results' / 'live_chat.sqlite'
OBS_CONFIG = ROOT / 'backend' / 'observation' / 'config.json'


def observation_settings():
    """Allow the local dashboard and chat service to share one observation store."""
    config = json.loads(OBS_CONFIG.read_text())
    override = os.environ.get('IHK_OBSERVATION_DB_PATH')
    if override:
        config['database']['path'] = str(Path(override).expanduser().resolve())
    return config


def settings():
    values = {}
    path = ROOT / 'backend' / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def chat_db():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS chat_sessions (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    db.execute('CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    return db


def reply(session_id, question, order_number=None):
    if not isinstance(question, str) or not 0 < len(question.strip()) <= 2000:
        raise ValueError('A message of up to 2000 characters is required')
    if session_id is not None and (not isinstance(session_id, str) or not re.fullmatch('[a-f0-9]{32}', session_id)):
        raise ValueError('Invalid session ID')
    with chat_db() as db:
        if session_id and not db.execute('SELECT 1 FROM chat_sessions WHERE id=?', (session_id,)).fetchone():
            raise ValueError('Unknown chat session')
        if not session_id:
            session_id = uuid4().hex
            db.execute('INSERT INTO chat_sessions (id,user_id) VALUES (?,0)', (session_id,))
        history = [dict(row) for row in db.execute('SELECT role,content FROM chat_messages WHERE session_id=? ORDER BY id', (session_id,))]
        db.execute('INSERT INTO chat_messages (session_id,role,content) VALUES (?,?,?)', (session_id,'user',question))
    config_values = settings()
    provider=chat_provider.get()
    key = os.getenv('GEMINI_API_KEY') or config_values.get('GEMINI_API_KEY')
    model = os.getenv('GEMINI_MODEL') or config_values.get('GEMINI_MODEL', 'gemini-2.5-flash')
    if provider=='gemini':
        if not key:raise RuntimeError('Gemini API key not configured')
        if not re.fullmatch('[A-Za-z0-9._-]+', model):raise RuntimeError('Invalid Gemini model')
    policy = policy_context(question)
    instructions = ('You are a helpful Shoply customer support assistant. Answer in English. '
                    'Start naturally and help the customer explain their issue. '
                    'There is no product catalog, order database or invoice system available. '
                    'Do not claim to look up orders, issue invoices, verify payments, process refunds or take actions. '
                    'Ask for relevant details when needed and suggest human support for account-specific actions. '
                    'Keep answers concise, friendly and clear. Use plain text without Markdown.')
    if policy['context']:
        instructions += '\n\n' + policy['context']
    if provider=='local':
        return local_reply(session_id,question,history,instructions)
    if provider=='openai':
        return openai_reply(session_id,question,history,instructions,config_values)
    contents = [{'role': 'user' if h['role']=='user' else 'model', 'parts': [{'text': h['content']}]} for h in history]
    contents.append({'role': 'user', 'parts': [{'text': question}]})
    payload = {'systemInstruction': {'parts': [{'text': instructions}]},
               'contents': contents, 'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 512}}
    obs = observation_settings()
    observation_id = uuid4().hex
    request_record = {'session_id': session_id, 'question': question, 'history': history, 'model': model}
    try:
        store.start(obs, ident=observation_id, source='chat', provider='gemini', model=model,
                    request=request_record, run_id=session_id, created_at=store.timestamp())
    except Exception:
        pass
    try:
        request = Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
                          data=json.dumps(payload).encode(), method='POST',
                          headers={'Content-Type':'application/json','x-goog-api-key':key})
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
        parts = result['candidates'][0]['content']['parts']
        attachments=[]
        tool_events=[]
        answer=''.join(part.get('text','') for part in parts).strip()
        if not answer:
            raise RuntimeError('Gemini returned no answer')
        with chat_db() as db:
            db.execute('INSERT INTO chat_messages (session_id,role,content) VALUES (?,?,?)', (session_id,'model',answer))
        try:
            store.finish(obs, observation_id, {'answer':answer,'tool_calls':tool_events,'attachments':attachments}, None, store.timestamp())
        except Exception:
            pass
        return {'session_id':session_id,'answer':answer,'provider':'gemini','attachments':attachments}
    except Exception as error:
        try:
            store.finish(obs, observation_id, None, {'type':type(error).__name__}, store.timestamp())
        except Exception:
            pass
        raise


def openai_reply(session_id, question, history, instructions, config):
    """OpenAI Chat Completions for general customer support."""
    key=os.getenv('OPENAI_API_KEY') or config.get('OPENAI_API_KEY')
    model=os.getenv('OPENAI_MODEL') or config.get('OPENAI_MODEL','gpt-4.1-mini')
    if not key:raise RuntimeError('OpenAI API key not configured')
    if not re.fullmatch('[A-Za-z0-9._-]+',model):raise RuntimeError('Invalid OpenAI model')
    tools=[]
    messages=[{'role':'system','content':instructions}]
    messages += [{'role':'user' if h['role']=='user' else 'assistant','content':h['content']} for h in history]
    messages.append({'role':'user','content':question})
    obs=observation_settings();observation_id=uuid4().hex
    try:store.start(obs,ident=observation_id,source='chat',provider='openai',model=model,request={'question':question,'history':history,},run_id=session_id,created_at=store.timestamp())
    except Exception:pass
    attachments=[];tool_events=[]
    try:
        for _ in range(3):
            payload={'model':model,'messages':messages,'temperature':0.2,'max_completion_tokens':512}
            req=Request('https://api.openai.com/v1/chat/completions',data=json.dumps(payload).encode(),method='POST',headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
            with urlopen(req,timeout=25) as response:result=json.load(response)
            choice=result['choices'][0]['message'];calls=choice.get('tool_calls') or []
            if not calls:
                answer=(choice.get('content') or '').strip()
                if not answer:raise RuntimeError('OpenAI returned no answer')
                with chat_db() as db:db.execute('INSERT INTO chat_messages(session_id,role,content) VALUES (?,?,?)',(session_id,'model',answer))
                try:store.finish(obs,observation_id,{'answer':answer,'tool_calls':tool_events,'attachments':attachments},None,store.timestamp())
                except Exception:pass
                return {'session_id':session_id,'answer':answer,'provider':'openai','attachments':attachments}
            raise RuntimeError('Unexpected tool call from model')
        raise RuntimeError('Too many tool calls')
    except Exception as exc:
        try:store.finish(obs,observation_id,None,{'type':type(exc).__name__},store.timestamp())
        except Exception:pass
        raise


def local_reply(session_id, question, history, instructions):
    """General customer chat via the local MLX OpenAI-compatible endpoint."""
    endpoint = 'http://127.0.0.1:18642/v1/chat/completions'
    model = 'mlx-community/Qwen3-4B-Instruct-2507-4bit'
    tools = []
    messages = [{'role': 'system', 'content': instructions}]
    messages.extend({'role': 'user' if h['role'] == 'user' else 'assistant', 'content': h['content']} for h in history)
    messages.append({'role': 'user', 'content': question})
    obs = observation_settings()
    ident = uuid4().hex
    try:
        store.start(obs, ident=ident, source='chat', provider='local', model=model,
                    request={'question': question, 'history': history}, run_id=session_id, created_at=store.timestamp())
    except Exception:
        pass
    attachments, tool_events = [], []
    try:
        for _ in range(4):
            payload = {'model': model, 'messages': messages, 'max_tokens': 512, 'stream': False}
            request = Request(endpoint, data=json.dumps(payload).encode(), method='POST', headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=90) as response:
                result = json.load(response)
            message = result['choices'][0]['message']
            calls = message.get('tool_calls') or []
            if not calls:
                answer = (message.get('content') or '').replace('<|im_end|>', '').strip()
                if not answer:
                    raise RuntimeError('Local model returned no answer')
                with chat_db() as db:
                    db.execute('INSERT INTO chat_messages(session_id,role,content) VALUES (?,?,?)', (session_id, 'model', answer))
                try:
                    store.finish(obs, ident, {'answer': answer, 'tool_calls': tool_events, 'attachments': attachments}, None, store.timestamp())
                except Exception:
                    pass
                return {'session_id': session_id, 'answer': answer, 'provider': 'local', 'attachments': attachments}
            raise RuntimeError('Unexpected tool call from local model')
        raise RuntimeError('Too many local tool calls')
    except Exception as error:
        try:
            store.finish(obs, ident, None, {'type': type(error).__name__}, store.timestamp())
        except Exception:
            pass
        raise
