"""Bounded multi-ticket evaluation requests to the loopback Qwen server."""
import json
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from uuid import uuid4
from backend.observation.tracing import best_effort, _configuration, _run
from backend.observation import store
from backend.evaluation.batching import pack, parse_results, instructions
from backend.evaluation.config import ModelLimits
from backend.llms.gemini import configured_categories
from backend.llms.local import DEFAULT_LOCAL_ENDPOINT, DEFAULT_LOCAL_MODEL
from backend.llms.retry import LLMError

# Conservative operational budgets; not claims about the model's official limits.
LIMITS = ModelLimits(context_tokens=8192, output_tokens=4096, max_tickets=None,
                     input_budget=5000, answer_tokens_per_ticket=80, reserve_tokens=1024)


def run(tickets, method, env, pause, progress=None):
    endpoint = env.get('LOCAL_LLM_ENDPOINT', DEFAULT_LOCAL_ENDPOINT)
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or not parsed.port or parsed.path != '/v1/chat/completions' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Local batch endpoint must be a loopback chat-completions URL')
    model = env.get('LOCAL_LLM_MODEL', DEFAULT_LOCAL_MODEL)
    categories = configured_categories(env.get('LLM_CATEGORIES', ''))
    prompt = instructions('local', method['prompt_version'], categories)
    batches = list(pack(tickets, prompt, LIMITS))
    timeout = float(env.get('LOCAL_LLM_TIMEOUT_SECONDS', '120'))
    if not 1 <= timeout <= 600:
        raise ValueError('Invalid local batch timeout')
    results = []
    execution_id = (_run.get() or {}).get('id') or uuid4().hex
    attempts = 0
    def emit():
        if progress:
            progress({'completed':len(results), 'total':len(tickets), 'batches':len(batches),
                      'requests':attempts, 'retries':0, 'errors':sum(bool(row[3]) for row in results),
                      'metadata_requests':0, 'limits_source':'local conservative configuration'})
    def classify(items):
        nonlocal attempts
        attempts += 1
        body = {'model':model, 'stream':False, 'temperature':0,
                'max_tokens':min(LIMITS.output_tokens, 128 + len(items)*LIMITS.answer_tokens_per_ticket),
                'messages':[{'role':'system','content':prompt},
                            {'role':'user','content':json.dumps({'tickets':items},ensure_ascii=False)}]}
        request = Request(endpoint, data=json.dumps(body).encode('utf-8'),
                          headers={'Content-Type':'application/json'}, method='POST')
        observation = best_effort(_configuration, 'evaluation')
        ident = uuid4().hex
        run_id = execution_id
        run_metadata = {'run_kind':'batch',
                        'ticket_count':len(tickets), 'batch':True}
        if observation:
            best_effort(store.start, observation, ident=ident, source='evaluation', provider='local',
                        model=model, request={'tickets':items, 'prompt_version':method['prompt_version'],
                        'batch_size':len(items), '_observation':run_metadata},
                        run_id=run_id, created_at=store.timestamp())
        try:
            with urlopen(request, timeout=timeout) as response:
                envelope = json.load(response)
            choice = envelope['choices'][0]
            if choice.get('finish_reason') != 'stop':
                raise LLMError('Incomplete local batch generation')
            content = choice['message']['content'].strip().replace('<|im_end|>', '').strip()
            if content.startswith('```'):
                content = content.split('\n',1)[1].rsplit('```',1)[0].strip()
            answers = parse_results(json.loads(content), items, categories)
            if observation:
                best_effort(store.finish, observation, ident,
                            {'results':[{'id':item['id'],'category':category,'confidence':confidence}
                                        for item,(category,confidence) in zip(items,answers)],
                             'usage':envelope.get('usage',{})}, None, store.timestamp())
            return [(category,confidence,'local:'+model+':batch-v1','') for category,confidence in answers]
        except Exception as exc:
            if observation:
                best_effort(store.finish, observation, ident, None,
                            {'type':type(exc).__name__}, store.timestamp())
            # Retry smaller groups rather than silently accepting missing IDs.
            if len(items)>1:
                middle=len(items)//2
                return classify(items[:middle])+classify(items[middle:])
            return [('FEHLER',0.0,'local:'+model+':batch-v1',str(exc)[:250])]
    emit()
    for items in batches:
        results.extend(classify(items))
        emit()
    return results
