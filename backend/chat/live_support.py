"""Local demonstration handoff queue, backed by SQLite and scoped to a session token.

This is not a production authentication mechanism: the employee dashboard is a trusted
local demonstration client and must be protected before public deployment.
"""
import sqlite3
from pathlib import Path
from uuid import uuid4

DB=Path(__file__).resolve().parents[2]/'results'/'live_chat.sqlite'

def connect():
    db=sqlite3.connect(DB,timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('''CREATE TABLE IF NOT EXISTS support_requests (
      id TEXT PRIMARY KEY, customer_token TEXT NOT NULL, status TEXT NOT NULL,
      employee TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('''CREATE TABLE IF NOT EXISTS support_messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
      sender TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    return db

def create(history=None):
    history=history or []
    if not isinstance(history,list) or len(history)>100:raise ValueError("Invalid conversation history")
    with connect() as db:
        ident=uuid4().hex; token=uuid4().hex
        db.execute('INSERT INTO support_requests(id,customer_token,status) VALUES (?,?,?)',(ident,token,'waiting'))
        for item in history:
            if not isinstance(item,dict) or item.get('sender') not in ('customer','ai') or not isinstance(item.get('content'),str) or len(item['content'])>4000:raise ValueError('Invalid conversation message')
            if item['content'].strip():db.execute('INSERT INTO support_messages(request_id,sender,content) VALUES (?,?,?)',(ident,item['sender'],item['content'].strip()))
    return {'id':ident,'customer_token':token,'status':'waiting'}

def read(ident,token=None,staff=False):
    with connect() as db:
        row=db.execute('SELECT * FROM support_requests WHERE id=?',(ident,)).fetchone()
        if not row or (not staff and row['customer_token']!=token): raise LookupError('Chat not found')
        msgs=[dict(r) for r in db.execute('SELECT id,sender,content,created_at FROM support_messages WHERE request_id=? ORDER BY id',(ident,))]
    return {'id':ident,'status':row['status'],'employee':row['employee'],'messages':msgs}

def queue():
    with connect() as db:
        rows=[dict(r) for r in db.execute("SELECT id,status,employee,created_at FROM support_requests WHERE status IN ('waiting','active') ORDER BY created_at,id")]
    return {'requests':rows,'waiting':sum(r['status']=='waiting' for r in rows)}

def accept(ident):
    with connect() as db:
        result=db.execute("UPDATE support_requests SET status='active',employee='Anna' WHERE id=? AND status='waiting'",(ident,))
        if result.rowcount!=1: raise ValueError('Chat is no longer waiting')
    return read(ident,staff=True)

def message(ident,sender,content,token=None):
    if not isinstance(content,str) or not 0<len(content.strip())<=2000: raise ValueError('Message must be 1–2000 characters')
    with connect() as db:
        row=db.execute('SELECT status,customer_token FROM support_requests WHERE id=?',(ident,)).fetchone()
        if not row or (sender=='customer' and row['customer_token']!=token):raise LookupError('Chat not found')
        if row['status']!='active':raise ValueError('Chat is not active')
        db.execute('INSERT INTO support_messages(request_id,sender,content) VALUES (?,?,?)',(ident,sender,content.strip()))
    return read(ident,token,staff=sender=='employee')

def close(ident,token=None,staff=False):
    with connect() as db:
        row=db.execute('SELECT customer_token FROM support_requests WHERE id=?',(ident,)).fetchone()
        if not row or (not staff and row['customer_token']!=token):raise LookupError('Chat not found')
        db.execute("UPDATE support_requests SET status='closed' WHERE id=?",(ident,))
    return read(ident,token,staff)


def close_open_demo_sessions():
    """End stale demo conversations when the support dashboard is reloaded."""
    with connect() as db:
        result=db.execute("UPDATE support_requests SET status='closed' WHERE status IN ('waiting','active')")
        return {'closed':result.rowcount}
