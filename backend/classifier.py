"""Transparent rule-based classification baseline for the first sprint.

The confidence score measures rule evidence; it is NOT a calibrated
probability or a trained model's accuracy. The dataset/model comparison
will replace or evaluate this adapter in a later sprint.
"""

from dataclasses import dataclass
import re

MODEL_VERSION = "keyword-baseline-v1"
REVIEW_THRESHOLD = 0.75

_RULES = {
    "Returns": {
        "damaged": 3, "broken": 3, "defective": 3, "refund": 3,
        "return": 3, "faulty": 3, "retoure": 3, "rückgabe": 3,
        "erstattung": 3, "kaputt": 3, "defekt": 3,
    },
    "Shipping": {
        "shipping": 3, "shipment": 3, "delivery": 3, "tracking": 3,
        "package": 2, "parcel": 2, "late": 1, "versand": 3,
        "lieferung": 3, "sendung": 2, "paket": 2,
    },
    "Billing": {
        "invoice": 3, "charged": 3, "billing": 3, "payment": 3,
        "bill": 2, "credit card": 2, "rechnung": 3,
        "zahlung": 3, "abbuchung": 3,
    },
    "Account": {
        "password": 3, "login": 3, "account": 2, "sign in": 3,
        "passwort": 3, "anmelden": 3, "konto": 2,
    },
    "Technical": {
        "error": 3, "crash": 3, "bug": 3, "not working": 3,
        "doesn't work": 3, "fehler": 3, "absturz": 3,
        "funktioniert nicht": 3,
    },
    "Orders": {
        "order": 1, "purchase": 2, "cancel": 3, "cancelled": 3,
        "cancel my order": 4, "change my order": 4, "modify my order": 4,
        "order status": 4, "order confirmation": 4, "wrong item": 3,
        "placed an order": 4, "ordered": 2,
        "cancellation": 3, "bestellung": 1, "stornierung": 3,
        "bestellstatus": 4, "bestellung ändern": 4, "bestellung stornieren": 4,
        "falscher artikel": 3, "bestellt": 2,
    },
}

_REPLIES = {
    "Returns": "I'm sorry there was a problem with your item. Our team can help you review the return or refund options.",
    "Shipping": "Thanks for contacting us. Our team can check your shipment details and provide an update.",
    "Billing": "Thanks for letting us know. Our team can look into the payment or invoice issue.",
    "Account": "We can help with your account access. Please do not share your password in this ticket.",
    "Technical": "Thanks for reporting the issue. Our support team will review the details and suggest next steps.",
    "Orders": "Thanks for reaching out about your order. Our team can review the order details and available options.",
    "General": "Thanks for your message. A team member will review your request and get back to you.",
}


@dataclass(frozen=True)
class PredictionResult:
    category: str
    confidence: float
    model_version: str


def predict_ticket(text: str) -> PredictionResult:
    """Return a deterministic baseline label, heuristic score and version."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Ticket text must be a non-empty string")

    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    scores = {}
    for category, keywords in _RULES.items():
        score = sum(
            weight
            for phrase, weight in keywords.items()
            if re.search(r"\b" + re.escape(phrase) + r"\b", normalized)
        )
        if score:
            scores[category] = score

    if not scores:
        return PredictionResult("General", 0.25, MODEL_VERSION)

    ranking = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    category, top = ranking[0]
    second = ranking[1][1] if len(ranking) > 1 else 0
    margin = top - second

    if margin == 0:
        confidence = 0.45
    elif top >= 3 and margin >= 2:
        confidence = 0.90
    elif top >= 3:
        confidence = 0.80
    elif top >= 2 and margin >= 2:
        confidence = 0.78
    else:
        confidence = 0.65

    return PredictionResult(category, confidence, MODEL_VERSION)


def suggest_customer_reply(category: str) -> str:
    """Return a bounded template suggestion, never a confirmed reply."""
    return _REPLIES.get(category, _REPLIES["General"])


# Explicit adapter for the 11 Bitext training labels. The existing UI labels
# remain stable; ambiguous mappings are intentionally not guessed.
_DATASET_LABELS = {
    "Shipping": "SHIPPING",
    "Billing": "PAYMENT",
    "Account": "ACCOUNT",
    "Orders": "ORDER",
}


def dataset_label_for(category: str):
    """Return a safe Bitext label or None when human mapping is required.

    Returns, Technical and General do not map unambiguously to Bitext labels.
    Billing can also involve INVOICE, so PAYMENT is a provisional mapping.
    """
    return _DATASET_LABELS.get(category)
