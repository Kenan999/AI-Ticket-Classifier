"""Human-in-the-loop review validation and CSV feedback storage."""

import csv
from datetime import datetime, timezone
from pathlib import Path


class ReviewError(ValueError):
    """A user-supplied review is incomplete or invalid."""


_CSV_FIELDS = [
    "request_id",
    "predicted_label",
    "final_label",
    "decision",
    "reviewer",
    "comment",
    "model_version",
    "confidence",
    "final_reply",
    "reviewed_at",
]


def _text(value, field, max_length, required=True):
    if not isinstance(value, str):
        raise ReviewError("{} must be a string".format(field))
    value = value.strip()
    if required and not value:
        raise ReviewError("{} must not be empty".format(field))
    if len(value) > max_length:
        raise ReviewError("{} must be at most {} characters".format(field, max_length))
    return value


def save_review(case, payload, csv_path):
    """Validate an explicit human decision, persist feedback and return final result.

    Decision "approve" keeps the suggested label; "correct" requires a human
    final label and an explicitly written final reply. Unreviewed suggestions
    are never returned as confirmed by the classification endpoint.
    """
    decision = payload.get("decision")
    if decision not in ("approve", "correct"):
        raise ReviewError("decision must be approve or correct")

    reviewer = _text(payload.get("reviewer"), "reviewer", 100)
    comment = _text(payload.get("comment", ""), "comment", 1000, required=False)

    if decision == "correct":
        final_category = _text(payload.get("final_category"), "final_category", 100)
        final_reply = _text(payload.get("customer_reply"), "customer_reply", 2000)
    else:
        if "final_category" in payload and payload["final_category"] != case["category"]:
            raise ReviewError("Use decision=correct to change the category")
        final_category = case["category"]
        final_reply = _text(
            payload.get("customer_reply", case["customer_reply"]),
            "customer_reply",
            2000,
        )

    reviewed_at = datetime.now(timezone.utc).isoformat()
    record = {
        "request_id": case["ticket_id"],
        "predicted_label": case["category"],
        "final_label": final_category,
        "decision": decision,
        "reviewer": reviewer,
        "comment": comment,
        "model_version": case["model_version"],
        "confidence": case["confidence"],
        "final_reply": final_reply,
        "reviewed_at": reviewed_at,
    }
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(record)

    return {
        "ticket_id": case["ticket_id"],
        "status": "reviewed",
        "decision": decision,
        "predicted_category": case["category"],
        "final_category": final_category,
        "customer_reply": final_reply,
        "reply_confirmed": True,
        "reviewer": reviewer,
        "model_version": case["model_version"],
        "reviewed_at": reviewed_at,
    }
