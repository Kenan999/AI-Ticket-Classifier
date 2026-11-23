"""Local observation receiver. Run with python -m backend.observation.service."""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, request
from backend.observation.database import DEFAULT_CONFIG, initialize_database
from backend.observation.store import clean, schema


def create_app(config_path=DEFAULT_CONFIG):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    path = initialize_database(config_path)
    with closing(sqlite3.connect(path)) as db, db:
        schema(db)

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            abort(400, "JSON object required")
        return value

    @app.get("/health")
    def health():
        with closing(sqlite3.connect(path)) as db:
            db.execute("SELECT 1 FROM observations LIMIT 1").fetchone()
        return jsonify(status="ok")

    @app.post("/observations")
    def start():
        value = body()
        if value.get("source") not in {"application", "chat", "evaluation"}:
            abort(400, "source must be application, chat, or evaluation")
        if any(not isinstance(value.get(k), str) or not 0 < len(value[k]) <= 200
               for k in ("provider", "model")) or not isinstance(value.get("request"), dict):
            abort(400, "provider, model and request object required")
        ident = str(uuid.uuid4())
        run_id = value.get("run_id", ident)
        if not isinstance(run_id, str) or not 0 < len(run_id) <= 200:
            abort(400, "run_id must be a non-empty string up to 200 characters")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO observations (id,source,provider,model,request_json,created_at,run_id) VALUES (?,?,?,?,?,?,?)",
                       (ident, value["source"], value["provider"], value["model"],
                        json.dumps(clean(value["request"]), ensure_ascii=False),
                        datetime.now(timezone.utc).isoformat(), run_id))
        return jsonify(id=ident, run_id=run_id), 201

    @app.patch("/observations/<ident>")
    def finish(ident):
        value = body()
        if not any(value.get(k) is not None for k in ("response", "error")):
            abort(400, "response or error required")
        with closing(sqlite3.connect(path)) as db, db:
            found = db.execute("SELECT completed_at FROM observations WHERE id=?", (ident,)).fetchone()
            if found is None:
                abort(404)
            if found[0] is not None:
                abort(409, "Observation already completed")
            changed = db.execute(
                "UPDATE observations SET response_json=?,error_json=?,completed_at=? WHERE id=? AND completed_at IS NULL",
                (json.dumps(clean(value["response"])) if value.get("response") is not None else None,
                 json.dumps(clean(value["error"])) if value.get("error") is not None else None,
                 datetime.now(timezone.utc).isoformat(), ident))
            if changed.rowcount != 1:
                abort(409)
        return jsonify(id=ident, status="completed")

    return app


if __name__ == "__main__":
    settings = json.loads(Path(DEFAULT_CONFIG).read_text())["service"]
    if settings["host"] != "127.0.0.1":
        raise ValueError("Observation currently supports loopback access only")
    port = settings["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError("Invalid observation port")
    create_app().run(host=settings["host"], port=port, debug=False)
