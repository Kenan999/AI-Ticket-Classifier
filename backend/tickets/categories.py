"""Shared ticket categories and response data, independent of classifiers."""
from dataclasses import dataclass

REVIEW_THRESHOLD = 0.75
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


@dataclass(frozen=True)
class PredictionResult:
    category: str
    confidence: float
    model_version: str


def dataset_label_for(category):
    return category if category in DATASET_CATEGORIES else None
