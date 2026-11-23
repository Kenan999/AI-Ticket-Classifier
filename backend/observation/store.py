"""Shared local storage for the receiver and automatic request recording."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .database import PROJECT_ROOT


def clean(value, secrets=()):
    if isinstance(value, dict):
        return {k: clean(v, secrets) for k, v in value.items()
                if str(k).lower().replace("-", "_") not in {
                    "authorization", "api_key", "apikey", "x_goog_api_key",
                    "token", "access_token", "password", "secret", "headers", "cookie"}}
    if isinstance(value, list):
        return [clean(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def connect(config):
    settings = config["database"]
    if settings["type"] != "sqlite":
        raise ValueError("Observation requires SQLite")
    path = Path(settings["path"]).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout = min(0.1, max(0.0, float(config.get("recording", {}).get("sqlite_timeout_seconds", 0.05))))
    return sqlite3.connect(path, timeout=timeout)


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS observations (
        id TEXT PRIMARY KEY, source TEXT NOT NULL, provider TEXT NOT NULL,
        model TEXT NOT NULL, request_json TEXT NOT NULL, response_json TEXT,
        error_json TEXT, created_at TEXT NOT NULL, completed_at TEXT, run_id TEXT
    )""")
    if "run_id" not in {r[1] for r in db.execute("PRAGMA table_info(observations)")}:
        db.execute("ALTER TABLE observations ADD COLUMN run_id TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS observations_run ON observations(run_id)")


def start(config, *, ident, source, provider, model, request, run_id, created_at):
    with closing(connect(config)) as db, db:
        schema(db)
        db.execute("""INSERT INTO observations
            (id,source,provider,model,request_json,created_at,run_id)
            VALUES (?,?,?,?,?,?,?)""",
            (ident,source,provider,model,json.dumps(request,ensure_ascii=False),created_at,run_id))


def finish(config, ident, response, error, completed_at):
    with closing(connect(config)) as db, db:
        db.execute("""UPDATE observations SET response_json=?,error_json=?,completed_at=?
            WHERE id=? AND completed_at IS NULL""",
            (json.dumps(response,ensure_ascii=False) if response is not None else None,
             json.dumps(error,ensure_ascii=False) if error is not None else None,
             completed_at,ident))


def annotate_run(config, run_id, metadata):
    with closing(connect(config)) as db, db:
        for ident, raw in db.execute("SELECT id,request_json FROM observations WHERE run_id=?",(run_id,)).fetchall():
            request = json.loads(raw)
            request.setdefault("_observation", {}).update(metadata)
            db.execute("UPDATE observations SET request_json=? WHERE id=?",
                       (json.dumps(request,ensure_ascii=False),ident))
