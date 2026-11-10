"""Local JSON API for classification and human review.

Run from the repository root:
    python3 backend/app.py

The first-sprint API stores active cases in memory and review feedback in CSV.
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
except ImportError:  # Supports direct execution: python3 backend/app.py
    from classifier import REVIEW_THRESHOLD, predict_ticket, suggest_customer_reply, dataset_label_for
    from review import ReviewError, save_review


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
        }
        with lock:
            store_case(case)
        return jsonify(case)

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


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("BACKEND_PORT", "8001"))
    app.run(host="127.0.0.1", port=port, debug=False)
