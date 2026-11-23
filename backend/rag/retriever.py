"""Provider-selectable embeddings with isolated local SQLite vector indexes."""
import json
import math
import os
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = Path(__file__).with_name('knowledge')
INDEX = ROOT / 'results' / 'rag_vectors.sqlite3'


def config():
    values = {}
    for path in (ROOT / 'backend' / '.env', Path('/Users/kenanali/Documents/GitHub/AI-Ticket-Classifier-Backend/backend/.env')):
        if path.is_file():
            for line in path.read_text().splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, val = line.split('=', 1)
                    values[key.strip()] = val.strip().strip('"').strip("'")
            break
    return values


from .embeddings import embed as provider_embed, model_name
from .chunking import bounded_sections, MAX_INPUT_BYTES


def embed(text, task_type, provider='gemini'):
    return provider_embed(text, task_type, provider, credentials=config())


def index_path(provider):
    if provider not in ('gemini', 'openai', 'local'):
        raise ValueError('Unsupported embedding provider')
    return INDEX if provider == 'gemini' else ROOT / 'results' / ('rag_vectors_' + provider + '.sqlite3')


def document_chunks(path):
    """Stable, byte-budgeted chunks grouped by Markdown section."""
    content = path.read_text(encoding='utf-8')
    doc_id = path.relative_to(KNOWLEDGE).with_suffix('').as_posix()
    parts = content.split('\n## ')
    heading = parts[0].splitlines()[0].lstrip('# ')
    for number, part in enumerate(parts):
        section = part if number == 0 else '## ' + part
        title = heading if number == 0 else part.splitlines()[0].strip()
        # Reserve space for the title that is included in embedding input.
        budget = MAX_INPUT_BYTES - len((heading + ' / ' + title + '\n').encode('utf-8'))
        for part_number, chunk in enumerate(bounded_sections(section, budget)):
            yield (f'{doc_id}#section-{number:02d}-chunk-{part_number:02d}',
                   f'{heading} / {title}', chunk)


def index_documents(provider='gemini'):
    index = index_path(provider)
    index.parent.mkdir(parents=True, exist_ok=True)
    model = model_name(provider)
    with sqlite3.connect(index) as db:
        db.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, title TEXT, content TEXT, embedding TEXT, model TEXT)')
        desired = set()
        for path in sorted(KNOWLEDGE.rglob('*.md')):
            for ident, title, content in document_chunks(path):
                desired.add(ident)
                existing = db.execute('SELECT content,model FROM documents WHERE id=?', (ident,)).fetchone()
                if existing == (content, model):
                    continue
                vector = embed(title + '\n' + content, 'RETRIEVAL_DOCUMENT', provider)
                db.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)',
                           (ident, title, content, json.dumps(vector), model))
                db.commit()
        # Remove obsolete whole-document embeddings only after replacements succeeded.
        for (ident,) in db.execute('SELECT id FROM documents').fetchall():
            if ident not in desired:
                db.execute('DELETE FROM documents WHERE id=?', (ident,))
        return db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]


def retrieve(question, limit=2, provider=None):
    provider = provider or os.getenv("RAG_EMBEDDING_PROVIDER", "gemini")
    index = index_path(provider)
    model = model_name(provider)
    if not isinstance(question, str) or not question.strip():
        raise ValueError('A question is required')
    if not index.is_file():
        raise RuntimeError('Build the RAG index first')
    query = embed(question, 'RETRIEVAL_QUERY', provider)
    def cosine(a, b):
        denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
        return sum(x*y for x,y in zip(a,b)) / denominator if denominator else 0.0
    with sqlite3.connect(f'file:{index}?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id,title,content,embedding FROM documents WHERE model=?', (model,)).fetchall()
    if not rows:
        raise RuntimeError('No embeddings indexed for selected provider/model; rebuild this provider index')
    scored = [{'id': ident, 'title': title, 'text': content,
               'score': round(cosine(query, json.loads(vector)), 4)}
              for ident,title,content,vector in rows]
    return sorted(scored, key=lambda row: row['score'], reverse=True)[:limit]


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['index','search'])
    parser.add_argument('question', nargs='?')
    parser.add_argument('--provider', choices=['gemini','openai','local'], default='gemini')
    args = parser.parse_args()
    print(json.dumps(index_documents(args.provider) if args.action=='index' else retrieve(args.question, provider=args.provider), indent=2))
