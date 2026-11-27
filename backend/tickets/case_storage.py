"""SQLite case metadata, with a transactional migration of legacy JSON rows."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


@contextmanager
def connect(path):
    connection = sqlite3.connect(path, timeout=15)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize(path):
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS cases (ticket_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        existing = {row[1] for row in connection.execute('PRAGMA table_info(cases)')}
        for name, kind in [('created_at', 'TEXT'), ('updated_at', 'TEXT'),
                           ('category', 'TEXT'), ('status', 'TEXT'), ('confidence', 'REAL')]:
            if name not in existing:
                connection.execute(f'ALTER TABLE cases ADD COLUMN {name} {kind}')
        # Unknown historical dates stay NULL. Never invent an original creation date.
        for ticket_id, payload in connection.execute(
                'SELECT ticket_id,payload FROM cases WHERE category IS NULL OR status IS NULL OR confidence IS NULL').fetchall():
            case = json.loads(payload)
            connection.execute('UPDATE cases SET category=?,status=?,confidence=? WHERE ticket_id=?',
                               (case.get('category'), case.get('status'), case.get('confidence'), ticket_id))
        connection.execute('CREATE INDEX IF NOT EXISTS cases_created_at ON cases(created_at DESC)')
        connection.execute('CREATE INDEX IF NOT EXISTS cases_status ON cases(status)')
        connection.execute('CREATE INDEX IF NOT EXISTS cases_category ON cases(category)')


def decode(row):
    case = json.loads(row[0])
    case.update(created_at=row[1], updated_at=row[2])
    return case


def load(path, ticket_id):
    with connect(path) as connection:
        row = connection.execute('SELECT payload,created_at,updated_at FROM cases WHERE ticket_id=?',
                                 (ticket_id,)).fetchone()
    return decode(row) if row else None


def store(path, case):
    now = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        previous = connection.execute('SELECT created_at FROM cases WHERE ticket_id=?',
                                      (case['ticket_id'],)).fetchone()
        case['created_at'] = previous[0] if previous else now
        case['updated_at'] = now
        connection.execute('''INSERT INTO cases(ticket_id,payload,created_at,updated_at,category,status,confidence)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(ticket_id) DO UPDATE SET
            payload=excluded.payload,updated_at=excluded.updated_at,
            category=excluded.category,status=excluded.status,confidence=excluded.confidence''',
            (case['ticket_id'], json.dumps(case), case['created_at'], now,
             case['category'], case['status'], case['confidence']))


def list_cases(path, status=None, category=None):
    conditions, values = [], []
    for name, value in [('status', status), ('category', category)]:
        if value is not None:
            conditions.append(name + '=?')
            values.append(value)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    with connect(path) as connection:
        rows = connection.execute('SELECT payload,created_at,updated_at FROM cases' + where +
            ' ORDER BY created_at IS NULL, created_at DESC, rowid DESC', values).fetchall()
    return [decode(row) for row in rows]
