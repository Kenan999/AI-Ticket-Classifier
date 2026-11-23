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
from backend.chat.invoices.service import ensure_sample_invoices
from backend.chat.tools.invoices import DECLARATION as INVOICE_DECLARATION, execute as invoice_tool
from backend.chat.tools.orders import DECLARATION as ORDER_DECLARATION, execute as order_tool

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
    ensure_sample_invoices()
    with chat_db() as db:
        user = db.execute('SELECT id FROM users WHERE email=?', ('example.user@example.com',)).fetchone()
        if not user:
            raise ValueError('Customer not found')
        if session_id:
            session = db.execute('SELECT id FROM chat_sessions WHERE id=? AND user_id=?', (session_id, user['id'])).fetchone()
            if not session:
                raise ValueError('Unknown customer session')
        else:
            session_id = uuid4().hex
            db.execute('INSERT INTO chat_sessions (id,user_id) VALUES (?,?)', (session_id, user['id']))
        orders = [dict(row) for row in db.execute('SELECT order_number,item_name,status FROM orders WHERE user_id=?', (user['id'],))]
        if order_number and order_number not in {o['order_number'] for o in orders}:
            raise ValueError('Order not found for this customer')
        history = [dict(row) for row in db.execute('SELECT role,content FROM chat_messages WHERE session_id=? ORDER BY id', (session_id,))]
        db.execute('INSERT INTO chat_messages (session_id,role,content) VALUES (?,?,?)', (session_id, 'user', question))
    config_values = settings()
    provider=chat_provider.get()
    key = os.getenv('GEMINI_API_KEY') or config_values.get('GEMINI_API_KEY')
    model = os.getenv('GEMINI_MODEL') or config_values.get('GEMINI_MODEL', 'gemini-2.5-flash')
    if provider=='gemini':
        if not key:raise RuntimeError('Gemini API key not configured')
        if not re.fullmatch('[A-Za-z0-9._-]+', model):raise RuntimeError('Invalid Gemini model')
    policy = policy_context(question)
    instructions = ('You are Shoply customer support. Always answer in English. '
                    'Use only the verified order data supplied. Do not invent delivery dates, tracking numbers, '
                    'refunds or actions. Invoice records are SAMPLE ONLY, not real invoices or actual charges. '
                    'Use find_customer_invoice when an invoice is requested; never invent an invoice or PDF. '
                    'Use get_customer_order_status when asked about order progress, processing, shipping or delivery. '
                    'Never guess the current status or claim a delivery date that the tool does not provide. '
                    'Maintain context from the entire conversation. '
                    'Format responses for a customer chat UI using clear, short paragraphs and, only when useful, '
                    'simple labeled lines. Never output Markdown syntax such as **, *, #, backticks, '
                    'or Markdown links. Do not print raw URLs or duplicate attachment links in the answer; '
                    'the interface displays tool-returned PDF files as clickable attachments. '
                    'Avoid repeating invoice details unnecessarily. Do not claim a PDF is attached unless the tool returned it.')
    # A duplicate charge is a payment issue, not an invoice request. Do not
    # offer invoice tools or fabricate invoice attachments for payment disputes.
    payment_dispute = bool(re.search(
        r'\b(charged twice|paid twice|double charg(?:e|ed)|duplicate (?:charge|payment)|'
        r'charged two times|doppelt (?:bezahlt|abgebucht)|zweimal (?:bezahlt|abgebucht))\b',
        question, re.IGNORECASE))
    if payment_dispute:
        instructions += ('\nThe customer reports a duplicate payment. Address the PAYMENT issue directly. '
                         'Do not offer an invoice or call invoice tools unless the customer explicitly asks '
                         'for an invoice. Do not claim you can verify or reverse charges without a payment '
                         'transaction tool. Ask for the affected order and recommend human payment support.')
    if policy['context']:
        instructions += '\n\n' + policy['context']
    if provider=='local':
        return local_reply(session_id,question,user['id'],history,orders,instructions,allow_invoice=not payment_dispute)
    if provider=='openai':
        return openai_reply(session_id,question,user['id'],history,orders,instructions,config_values,allow_invoice=not payment_dispute)
    contents = [{'role': 'user' if h['role']=='user' else 'model', 'parts': [{'text': h['content']}]} for h in history]
    contents.append({'role': 'user', 'parts': [{'text': question}]})
    payload = {'systemInstruction': {'parts': [{'text': instructions + '\nVerified orders: ' + json.dumps(orders)}]},
               'contents': contents, 'tools': [{'functionDeclarations': INVOICE_DECLARATION['functionDeclarations'] + ORDER_DECLARATION['functionDeclarations']}], 'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 512}}
    obs = observation_settings()
    observation_id = uuid4().hex
    request_record = {'session_id': session_id, 'question': question, 'history': history, 'orders': orders, 'model': model}
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
        for part in parts:
            call=part.get('functionCall')
            if not call:
                continue
            with chat_db() as db:
                if call.get('name') == 'find_customer_invoice':
                    tool_result=invoice_tool(db, user['id'], call.get('args') or {})
                elif call.get('name') == 'get_customer_order_status':
                    tool_result=order_tool(db, user['id'], call.get('args') or {})
                else:
                    tool_result={'error':'Unknown tool'}
            tool_events.append({'tool':call.get('name'),'arguments':call.get('args') or {},'result':tool_result})
            if 'pdf_url' in tool_result:
                attachments.append({'name':tool_result['invoice_number']+'.pdf',
                    'url':tool_result['pdf_url'],'label':'Sample invoice for '+tool_result['product']})
            contents.append({'role':'model','parts':parts})
            contents.append({'role':'user','parts':[{'functionResponse':{'name':call.get('name'), 'response':tool_result}}]})
        if tool_events:
            followup={'systemInstruction':payload['systemInstruction'], 'contents':contents,
                      'generationConfig':payload['generationConfig']}
            request2=Request('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
                             data=json.dumps(followup).encode(),method='POST',
                             headers={'Content-Type':'application/json','x-goog-api-key':key})
            with urlopen(request2,timeout=20) as response:
                result=json.load(response)
            parts=result['candidates'][0]['content']['parts']
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


def openai_reply(session_id, question, user_id, history, orders, instructions, config, allow_invoice=True):
    """OpenAI Chat Completions with the same customer-scoped order/invoice tools."""
    key=os.getenv('OPENAI_API_KEY') or config.get('OPENAI_API_KEY')
    model=os.getenv('OPENAI_MODEL') or config.get('OPENAI_MODEL','gpt-4.1-mini')
    if not key:raise RuntimeError('OpenAI API key not configured')
    if not re.fullmatch('[A-Za-z0-9._-]+',model):raise RuntimeError('Invalid OpenAI model')
    declarations=(INVOICE_DECLARATION['functionDeclarations'] if allow_invoice else [])+ORDER_DECLARATION['functionDeclarations']
    tools=[]
    for item in declarations:
        params=json.loads(json.dumps(item['parameters']))
        def normalize(node):
            if isinstance(node,dict):
                if 'type' in node:node['type']=node['type'].lower()
                for value in node.values():normalize(value)
            elif isinstance(node,list):
                for value in node:normalize(value)
        normalize(params)
        tools.append({'type':'function','function':{'name':item['name'],'description':item['description'],'parameters':params}})
    messages=[{'role':'system','content':instructions+'\nVerified orders: '+json.dumps(orders)}]
    messages += [{'role':'user' if h['role']=='user' else 'assistant','content':h['content']} for h in history]
    messages.append({'role':'user','content':question})
    obs=observation_settings();observation_id=uuid4().hex
    try:store.start(obs,ident=observation_id,source='chat',provider='openai',model=model,request={'question':question,'history':history,'orders':orders},run_id=session_id,created_at=store.timestamp())
    except Exception:pass
    attachments=[];tool_events=[]
    try:
        for _ in range(3):
            payload={'model':model,'messages':messages,'tools':tools,'temperature':0.2,'max_completion_tokens':512}
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
            messages.append(choice)
            for call in calls:
                name=call['function']['name'];args=json.loads(call['function'].get('arguments') or '{}')
                with chat_db() as db:
                    if name=='find_customer_invoice':value=invoice_tool(db,user_id,args)
                    elif name=='get_customer_order_status':value=order_tool(db,user_id,args)
                    else:value={'error':'Unknown tool'}
                tool_events.append({'tool':name,'arguments':args,'result':value})
                if 'pdf_url' in value:attachments.append({'name':value['invoice_number']+'.pdf','url':value['pdf_url'],'label':'Sample invoice for '+value['product']})
                messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(value)})
        raise RuntimeError('Too many tool calls')
    except Exception as exc:
        try:store.finish(obs,observation_id,None,{'type':type(exc).__name__},store.timestamp())
        except Exception:pass
        raise


def local_reply(session_id, question, user_id, history, orders, instructions, allow_invoice=True):
    """Customer-scoped tool calling via the local MLX OpenAI-compatible endpoint."""
    endpoint = 'http://127.0.0.1:18642/v1/chat/completions'
    model = 'mlx-community/Qwen3-4B-Instruct-2507-4bit'
    declarations = (INVOICE_DECLARATION['functionDeclarations'] if allow_invoice else []) + ORDER_DECLARATION['functionDeclarations']
    tools = []
    for item in declarations:
        params = item['parameters'].copy()
        params['type'] = 'object'
        params['properties'] = {k: dict(v, type=v['type'].lower()) for k, v in params['properties'].items()}
        tools.append({'type': 'function', 'function': {'name': item['name'], 'description': item['description'], 'parameters': params}})
    messages = [{'role': 'system', 'content': instructions + '\nVerified orders: ' + json.dumps(orders)}]
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
            payload = {'model': model, 'messages': messages, 'tools': tools, 'tool_choice': 'auto', 'max_tokens': 512, 'stream': False}
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
            messages.append({'role': 'assistant', 'content': message.get('content'), 'tool_calls': calls})
            for call in calls:
                fn = call.get('function') or {}
                name = fn.get('name')
                try:
                    args = json.loads(fn.get('arguments') or '{}')
                    if not isinstance(args, dict):
                        raise ValueError('Arguments must be an object')
                except (ValueError, TypeError):
                    args = None
                with chat_db() as db:
                    if args is None:
                        value = {'error': 'Invalid tool arguments'}
                    elif name == 'find_customer_invoice':
                        value = invoice_tool(db, user_id, args)
                    elif name == 'get_customer_order_status':
                        value = order_tool(db, user_id, args)
                    else:
                        value = {'error': 'Unknown tool'}
                tool_events.append({'tool': name, 'arguments': args, 'result': value})
                if 'pdf_url' in value:
                    attachments.append({'name': value['invoice_number'] + '.pdf', 'url': value['pdf_url'], 'label': 'Sample invoice for ' + value['product']})
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(value)})
        raise RuntimeError('Too many local tool calls')
    except Exception as error:
        try:
            store.finish(obs, ident, None, {'type': type(error).__name__}, store.timestamp())
        except Exception:
            pass
        raise
