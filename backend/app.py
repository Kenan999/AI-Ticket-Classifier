"""Local JSON API for classification and human review.

Run from the repository root:
    python3 backend/app.py

The API stores cases in SQLite and review feedback in CSV.
It is a local development service, not a public/authenticated deployment.
"""

import os
import json
import sqlite3
from pathlib import Path
import threading
import uuid

from flask import Flask, jsonify, request

try:
    from .classifier import REVIEW_THRESHOLD, predict_ticket, suggest_customer_reply, dataset_label_for
    from .review import ReviewError, save_review
    from .config import openai_api_key
    from .openai_classifier import DEFAULT_OPENAI_MODEL, classify_with_openai
    from .llm_classifier import DEFAULT_MODEL, LLMError, configured_categories, classify_with_gemini
except ImportError:  # Supports direct execution: python3 backend/app.py
    from classifier import REVIEW_THRESHOLD, predict_ticket, suggest_customer_reply, dataset_label_for
    from review import ReviewError, save_review
    from config import openai_api_key
    from openai_classifier import DEFAULT_OPENAI_MODEL, classify_with_openai
    from llm_classifier import DEFAULT_MODEL, LLMError, configured_categories, classify_with_gemini


PROVIDERS = ("baseline", "openai", "gemini")


def default_provider():
    provider = os.getenv("LLM_PROVIDER", "baseline").strip().lower()
    # Preserve the existing baseline behavior for unknown deployment settings.
    return provider if provider in PROVIDERS else "baseline"


def create_app(review_path=None, case_db_path=None):
    app = Flask(__name__)
    default_review_path = Path(__file__).resolve().parent.parent / "results" / "reviews.csv"
    app.config["REVIEW_PATH"] = Path(
        review_path if review_path is not None
        else os.getenv("REVIEW_CSV_PATH", str(default_review_path))
    )
    case_db = Path(case_db_path) if case_db_path is not None else app.config["REVIEW_PATH"].parent / "cases.sqlite"
    case_db.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.RLock()

    def connect_cases():
        connection = sqlite3.connect(case_db, timeout=15)
        connection.execute("CREATE TABLE IF NOT EXISTS cases (ticket_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        return connection

    with connect_cases() as connection:
        pass

    def load_case(ticket_id):
        with connect_cases() as connection:
            row = connection.execute("SELECT payload FROM cases WHERE ticket_id=?", (ticket_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def store_case(case):
        with connect_cases() as connection:
            connection.execute("INSERT OR REPLACE INTO cases(ticket_id,payload) VALUES (?,?)", (case["ticket_id"], json.dumps(case)))

    origins = {
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000,"
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    }

    def error(code, message, status=400):
        return jsonify({"error": {"code": code, "message": message}}), status

    @app.after_request
    def cors_for_local_frontend(response):
        origin = request.headers.get("Origin")
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Vary"] = "Origin"
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/providers")
    def providers():
        # Configuration presence is not a live provider health check.
        response = jsonify({
            "default_provider": default_provider(),
            "providers": [
                {"id": "baseline", "label": "Local rules", "configured": True},
                {"id": "openai", "label": "OpenAI", "configured": bool(openai_api_key())},
                {"id": "gemini", "label": "Gemini",
                 "configured": bool(os.getenv("GEMINI_API_KEY", "").strip())},
            ],
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/classify")
    def classify():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error("invalid_json", "Send a JSON object with a text field")
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            return error("invalid_text", "text must be a non-empty string")
        text = text.strip()
        if len(text) > 4000:
            return error("text_too_long", "text must be at most 4000 characters")

        explicit_provider = "provider" in data
        provider = data.get("provider") if explicit_provider else default_provider()
        if not isinstance(provider, str) or provider not in PROVIDERS:
            return error("invalid_provider", "provider must be baseline, openai or gemini")

        # Only this request selects the provider; never mutate process settings.
        used_provider = "baseline"
        prediction = None
        if provider != "baseline":
            api_key = (openai_api_key() if provider == "openai"
                       else os.getenv("GEMINI_API_KEY", "").strip())
            if not api_key:
                if explicit_provider:
                    return error("provider_not_configured",
                                 "Selected provider is not configured on the server", 503)
                app.logger.warning("%s selected but key missing; using baseline", provider)
            else:
                try:
                    adapter = classify_with_openai if provider == "openai" else classify_with_gemini
                    model = (os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
                             if provider == "openai" else os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
                    prediction = adapter(
                        text, api_key=api_key, categories=configured_categories(),
                        model=model, timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "8")),
                    )
                    used_provider = provider
                except (LLMError, ValueError, OverflowError) as exc:
                    # Never expose provider responses, ticket text or keys in errors.
                    app.logger.warning("%s classification unavailable (%s)", provider, type(exc).__name__)
                    if explicit_provider:
                        return error("provider_unavailable", "Selected provider could not classify the ticket", 502)
        if prediction is None:
            prediction = predict_ticket(text)
        review_required = prediction.confidence < REVIEW_THRESHOLD
        ticket_id = "T-" + uuid.uuid4().hex[:12].upper()
        case = {
            "ticket_id": ticket_id,
            "text": text,
            "category": prediction.category,
            "dataset_label": dataset_label_for(prediction.category),
            "confidence": prediction.confidence,
            "status": "human_review" if review_required else "classified",
            "customer_reply": suggest_customer_reply(prediction.category),
            "review_required": review_required,
            "reply_confirmed": False,
            "model_version": prediction.model_version,
            "requested_provider": provider,
            "provider": used_provider,
            "fallback_used": used_provider != provider,
        }
        with lock:
            store_case(case)
        return jsonify(case)

    @app.get("/cases")
    def cases_list():
        """Return all persisted cases for the support dashboard, newest first."""
        with lock:
            with connect_cases() as connection:
                rows = connection.execute(
                    "SELECT payload FROM cases ORDER BY rowid DESC"
                ).fetchall()
        return jsonify([json.loads(row[0]) for row in rows])

    @app.get("/case/<ticket_id>")
    def case_detail(ticket_id):
        with lock:
            case = load_case(ticket_id)
            if case is None:
                return error("not_found", "Unknown ticket", 404)
            return jsonify(case)

    @app.post("/review")
    def review():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error("invalid_json", "Send a JSON review object")
        ticket_id = data.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id:
            return error("invalid_ticket_id", "ticket_id is required")

        with lock:
            case = load_case(ticket_id)
            if case is None:
                return error("not_found", "Unknown ticket", 404)
            if case.get("reply_confirmed"):
                return error("already_reviewed", "Ticket has already been reviewed", 409)
            try:
                review_result = save_review(case, data, app.config["REVIEW_PATH"])
            except ReviewError as exc:
                return error("invalid_review", str(exc))
            except OSError:
                app.logger.exception("Could not write review feedback")
                return error("storage_error", "Review could not be saved", 500)

            case.update({
                "category": review_result["final_category"],
                "dataset_label": dataset_label_for(review_result["final_category"]),
                "customer_reply": review_result["customer_reply"],
                "status": "reviewed",
                "review_required": False,
                "reply_confirmed": True,
            })
            store_case(case)
        return jsonify(review_result)

    return app


def load_local_env():
    """Load only supported backend settings from the private .env file."""
    path = Path(__file__).resolve().parent / ".env"
    if not path.is_file():
        return
    allowed = {"LLM_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL",
               "LLM_TIMEOUT_SECONDS", "LLM_CATEGORIES"}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() in allowed:
            os.environ.setdefault(name.strip(), value.strip().strip('"\''))


app = create_app()

if __name__ == "__main__":
    load_local_env()
    port = int(os.getenv("BACKEND_PORT", "8001"))
    app.run(host="127.0.0.1", port=port, debug=False)
