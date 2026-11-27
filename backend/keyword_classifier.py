"""Deterministic nine-label Bitext baseline for customer support tickets.

Scores measure keyword evidence, not calibrated probabilities or accuracy.
Unclear/off-topic messages receive a low-confidence CONTACT label and require
human review; no unsupported tenth category is introduced.
"""

from dataclasses import dataclass
import re

MODEL_VERSION = "keyword-baseline-v2-nine-labels"
REVIEW_THRESHOLD = 0.75

# Keep category spelling and order aligned with data/processed/*.csv.
DATASET_CATEGORIES = (
    "ACCOUNT", "ORDER", "INVOICE", "CONTACT", "PAYMENT",
    "FEEDBACK", "REFUND", "DELIVERY", "SHIPPING",
)

# The same distinctions are included in Gemini and OpenAI prompts.
CATEGORY_GUIDANCE = (
    "ACCOUNT: account creation, access, passwords, profile. "
    "ORDER: placing, changing, cancelling or checking an order. "
    "INVOICE: invoice documents, copies, corrections or receipts. "
    "CONTACT: ways to reach support or request a human contact. "
    "PAYMENT: charges, payment methods, transactions or failed payments. "
    "FEEDBACK: suggestions, compliments, ratings or complaints. "
    "REFUND: returns, reimbursements, faulty or damaged goods. "
    "DELIVERY: delivery arrival, delays, tracking or missing parcels. "
    "SHIPPING: dispatch, shipping options, methods, costs or destinations. "
    "If unclear or unrelated, choose the closest of the nine with low confidence."
)

_RULES = {
    "ACCOUNT": {
        "password": 3, "password reset": 4, "login": 3, "log in": 3,
        "account": 2, "sign in": 3, "register": 2, "profile": 2,
        "passwort": 3, "anmelden": 3, "konto": 2, "registrieren": 2,
    },
    "ORDER": {
        "order": 1, "orders": 1, "purchase": 1, "placed an order": 4,
        "cancel my order": 4, "change my order": 4, "modify my order": 4,
        "order status": 4, "order confirmation": 4, "wrong item": 3,
        "ordered": 2, "cancellation": 2, "bestellung": 1,
        "bestellung ändern": 4, "bestellung stornieren": 4,
        "bestellstatus": 4, "stornierung": 3, "bestellt": 2,
    },
    "INVOICE": {
        "invoice": 3, "invoice copy": 4, "copy of my invoice": 4,
        "tax invoice": 4, "receipt": 3, "vat": 3, "billing statement": 3,
        "rechnung": 3, "rechnungsnummer": 3, "quittung": 3,
        "beleg": 2, "mehrwertsteuer": 3,
    },
    "CONTACT": {
        "contact": 3, "contact support": 4, "support agent": 4,
        "customer service": 3, "phone number": 3, "email address": 3,
        "speak to someone": 4, "talk to an agent": 4, "representative": 3,
        "human agent": 4, "kontakt": 3, "kundendienst": 3,
        "kundenservice": 3, "erreichen": 2, "telefonnummer": 3,
    },
    "PAYMENT": {
        "payment": 3, "pay": 2, "paid": 2, "charged": 3,
        "charged twice": 4, "duplicate charge": 4, "card": 2,
        "credit card": 3, "transaction": 3, "checkout": 2,
        "billing": 2, "zahlung": 3, "bezahlt": 2,
        "abbuchung": 3, "kreditkarte": 3,
    },
    "FEEDBACK": {
        "feedback": 4, "suggestion": 3, "complaint": 3, "review": 2,
        "rating": 3, "improvement": 2, "compliment": 3, "great service": 3,
        "bewertung": 3, "vorschlag": 3, "rückmeldung": 3,
        "lob": 3, "beschwerde": 3,
    },
    "REFUND": {
        "refund": 4, "return": 3, "returns": 3, "money back": 4,
        "reimbursement": 3, "damaged": 3, "broken": 3, "defective": 3,
        "faulty": 3, "retoure": 3, "rückgabe": 3, "erstattung": 3,
        "kaputt": 3, "defekt": 3, "zurückgeben": 3,
    },
    "DELIVERY": {
        "delivery": 3, "delivered": 3, "not arrived": 4,
        "arrived": 2, "tracking": 3, "tracking number": 3,
        "parcel": 2, "package": 2, "courier": 3, "late": 1,
        "lost parcel": 4, "missing package": 4, "lieferung": 3,
        "zugestellt": 3, "sendung": 2, "paket": 2, "lieferstatus": 3,
    },
    "SHIPPING": {
        "shipping": 3, "shipping cost": 4, "shipping fee": 4,
        "shipping method": 4, "shipping options": 4,
        "ship to": 4, "ship internationally": 4, "shipment": 2,
        "dispatch": 3, "international shipping": 4,
        "versand": 3, "versandkosten": 4, "versandart": 4,
        "versandoptionen": 4, "verschicken": 3,
    },
}

_REPLIES = {
    "ACCOUNT": "We can help with your account access. Please do not share your password in this ticket.",
    "ORDER": "Our team can review your order details and available options.",
    "INVOICE": "Our team can check your invoice or receipt and help with a correction.",
    "CONTACT": "A support team member will review your message and explain how to get in touch.",
    "PAYMENT": "Our team can investigate the payment or charge. Please do not share full card details.",
    "FEEDBACK": "Thank you for your feedback. Our team will review it.",
    "REFUND": "Our team can review your return or refund options.",
    "DELIVERY": "Our team can check the delivery status and tracking information.",
    "SHIPPING": "Our team can explain shipping methods, destinations and costs.",
}


@dataclass(frozen=True)
class PredictionResult:
    category: str
    confidence: float
    model_version: str


def predict_ticket(text: str) -> PredictionResult:
    """Return one of the nine dataset labels and an uncalibrated evidence score."""
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
        # Bitext has no GENERAL or TECHNICAL label. Keep low confidence for review.
        return PredictionResult("CONTACT", 0.25, MODEL_VERSION)

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
    """Return a bounded suggestion, never a confirmed reply."""
    return _REPLIES.get(category, _REPLIES["CONTACT"])


def dataset_label_for(category: str):
    """Return an identical Bitext label, or None for a historical legacy label."""
    return category if category in DATASET_CATEGORIES else None
