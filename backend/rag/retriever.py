"""Gemini embeddings + local SQLite vector index; no external vector packages."""
import json
import math
import os
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = Path(__file__).with_name('knowledge')
INDEX = ROOT / 'results' / 'rag_vectors.sqlite3'
EMBED_MODEL = 'gemini-embedding-001'


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


def embed(text, task_type):
    key = os.environ.get('GEMINI_API_KEY') or config().get('GEMINI_API_KEY')
    if not key:
        raise RuntimeError('Existing backend GEMINI_API_KEY is unavailable')
    payload = {'model': 'models/' + EMBED_MODEL,
               'content': {'parts': [{'text': text}]}, 'taskType': task_type}
    req = Request('https://generativelanguage.googleapis.com/v1beta/models/' + EMBED_MODEL + ':embedContent',
                  data=json.dumps(payload).encode(), method='POST',
                  headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
    with urlopen(req, timeout=25) as response:
        return json.load(response)['embedding']['values']


def document_chunks(path):
    """Stable section IDs and bounded embedding inputs; never split a paragraph mid-sentence."""
    content = path.read_text(encoding='utf-8')
    doc_id = path.relative_to(KNOWLEDGE).with_suffix('').as_posix()
    parts = content.split('\n## ')
    heading = parts[0].splitlines()[0].lstrip('# ')
    for number, part in enumerate(parts):
        section = part if number == 0 else '## ' + part
        title = heading if number == 0 else part.splitlines()[0].strip()
        yield (f'{doc_id}#section-{number:02d}', f'{heading} / {title}', section)


def index_documents():
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(INDEX) as db:
        db.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, title TEXT, content TEXT, embedding TEXT, model TEXT)')
        desired = set()
        for path in sorted(KNOWLEDGE.rglob('*.md')):
            for ident, title, content in document_chunks(path):
                desired.add(ident)
                existing = db.execute('SELECT content,model FROM documents WHERE id=?', (ident,)).fetchone()
                if existing == (content, EMBED_MODEL):
                    continue
                vector = embed(title + '\n' + content, 'RETRIEVAL_DOCUMENT')
                db.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)',
                           (ident, title, content, json.dumps(vector), EMBED_MODEL))
                db.commit()
        # Remove obsolete whole-document embeddings only after replacements succeeded.
        for (ident,) in db.execute('SELECT id FROM documents').fetchall():
            if ident not in desired:
                db.execute('DELETE FROM documents WHERE id=?', (ident,))
        return db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]


def retrieve(question, limit=2):
    if not isinstance(question, str) or not question.strip():
        raise ValueError('A question is required')
    if not INDEX.is_file():
        raise RuntimeError('Build the RAG index first')
    query = embed(question, 'RETRIEVAL_QUERY')
    def cosine(a, b):
        denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
        return sum(x*y for x,y in zip(a,b)) / denominator if denominator else 0.0
    with sqlite3.connect(f'file:{INDEX}?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id,title,content,embedding FROM documents').fetchall()
    scored = [{'id': ident, 'title': title, 'text': content,
               'score': round(cosine(query, json.loads(vector)), 4)}
              for ident,title,content,vector in rows]
    return sorted(scored, key=lambda row: row['score'], reverse=True)[:limit]


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['index','search'])
    parser.add_argument('question', nargs='?')
    args = parser.parse_args()
    print(json.dumps(index_documents() if args.action=='index' else retrieve(args.question), indent=2))
