"""Semantic retrieval of labeled training tickets; never index validation/test splits."""
import csv
import json
import math
import sqlite3
from pathlib import Path

from .retriever import ROOT
from .embeddings import embed as provider_embed, model_name

TRAIN = ROOT / 'data' / 'processed' / 'train.csv'
INDEX = ROOT / 'results' / 'rag_ticket_categories.sqlite3'
CATEGORIES = frozenset(('ACCOUNT', 'ORDER', 'INVOICE', 'CONTACT', 'PAYMENT', 'FEEDBACK', 'REFUND', 'DELIVERY', 'SHIPPING'))


def chunks(text, max_chars=800):
    """Sentence-aware chunks with bounded input; preserve short tickets intact."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    current = ''
    for sentence in sentences:
        for part in (sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars)):
            if current and len(current) + len(part) + 1 > max_chars:
                yield current
                current = ''
            current = (current + ' ' + part).strip()
    if current:
        yield current


def index_training(dataset=TRAIN, index=INDEX, limit=None, provider="local"):
    """Build/resume a semantic index. Explicit invocation required (embedding API costs)."""
    dataset, index = Path(dataset), Path(index)
    if dataset.name != 'train.csv':
        raise ValueError('Only train.csv may be indexed')
    index.parent.mkdir(parents=True, exist_ok=True)
    indexed = 0
    embedding_model = provider + ':' + model_name(provider)
    local_model = None
    local_encode = None
    if provider == 'local':
        from .local.model_loader import load_model, encode
        local_model, local_encode = load_model(), encode
    with sqlite3.connect(index) as db, dataset.open(newline='', encoding='utf-8') as file:
        db.execute('CREATE TABLE IF NOT EXISTS examples (id TEXT PRIMARY KEY, category TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL, model TEXT NOT NULL)')
        pending = []
        def flush():
            nonlocal indexed
            if not pending:
                return
            vectors = (local_encode(local_model, ['passage: ' + item[2] for item in pending])
                       if provider == 'local' else
                       [provider_embed(item[2], 'RETRIEVAL_DOCUMENT', provider=provider) for item in pending])
            db.executemany('INSERT OR REPLACE INTO examples VALUES (?,?,?,?,?)',
                           [(ident, category, content, json.dumps(vector), embedding_model)
                            for (ident, category, content), vector in zip(pending, vectors)])
            db.commit()
            indexed += len(pending)
            pending.clear()
        for row in csv.DictReader(file):
            category = row['label'].strip().upper()
            if category not in CATEGORIES:
                continue
            for number, text in enumerate(chunks(row['text'])):
                ident = f"{row['ticket_id']}#{number}"
                existing = db.execute('SELECT content,category,model FROM examples WHERE id=?', (ident,)).fetchone()
                if existing == (text, category, embedding_model):
                    continue
                pending.append((ident, category, text))
                if len(pending) >= 32:
                    flush()
                if limit is not None and indexed + len(pending) >= limit:
                    flush()
                    return indexed
        flush()
    return indexed


def retrieve_examples(issue, limit=5, index=INDEX, provider="local"):
    if not isinstance(issue, str) or not issue.strip():
        return []
    if not Path(index).is_file():
        raise RuntimeError('Training index not built; run index_training first')
    if provider == 'local':
        from .local.model_loader import load_model, encode
        query = encode(load_model(), ['query: ' + issue])[0]
    else:
        query = provider_embed(issue, 'RETRIEVAL_QUERY', provider=provider)
    embedding_model = provider + ':' + model_name(provider)
    with sqlite3.connect(f'file:{Path(index).resolve()}?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id,category,content,embedding FROM examples WHERE model=?', (embedding_model,)).fetchall()
    def cosine(vector):
        if len(vector) != len(query):
            return 0.0
        denominator = math.sqrt(sum(x*x for x in vector) * sum(x*x for x in query))
        return sum(a*b for a,b in zip(vector, query)) / denominator if denominator else 0.0
    matches = [{'id': ident, 'category': category, 'text': text, 'score': round(cosine(json.loads(vector)), 4)}
               for ident, category, text, vector in rows]
    return sorted(matches, key=lambda row: row['score'], reverse=True)[:limit]
