"""Evaluation V0 – Schritt 2: Testtickets durch den Klassifikator schicken.

Noch keine Metriken und kein CSV-Export. Nur: Ticket rein, Kategorie raus.

Starten aus dem Projekt-Root:
    python3 -m evaluation.evaluate
"""

from backend.classifier import predict_ticket

# Die 5 freigegebenen Testtickets.
# "expected" ist die Ground Truth, also unsere menschliche Einordnung.
TEST_TICKETS = [
    {
        "text": "I want to return the damaged lamp and get a refund.",
        "expected": "Returns",
    },
    {
        "text": (
            "Where is my parcel? The tracking number has not "
            "updated in five days."
        ),
        "expected": "Shipping",
    },
    {
        "text": "I was charged twice for the same invoice last month.",
        "expected": "Billing",
    },
    {
        "text": "I cannot sign in and my password reset link does not work.",
        "expected": "Account",
    },
    {
        "text": (
            "Every time I click checkout I get an error and the "
            "page does not load."
        ),
        "expected": "Technical",
    },
]


def run_evaluation(tickets=TEST_TICKETS):
    """Ruft predict_ticket() je Ticket auf und sammelt die Ergebnisse."""
    results = []
    for ticket in tickets:
        prediction = predict_ticket(ticket["text"])
        results.append({
            "text": ticket["text"],
            "expected": ticket["expected"],
            "predicted": prediction.category,
            "confidence": prediction.confidence,
            "model_version": prediction.model_version,
            "correct": prediction.category == ticket["expected"],
        })
    return results


def main():
    for number, result in enumerate(run_evaluation(), start=1):
        mark = "OK " if result["correct"] else "FALSCH"
        print(f"{mark} Ticket {number}")
        print(f"   Text:       {result['text']}")
        print(f"   Erwartet:   {result['expected']}")
        print(f"   Vorhersage: {result['predicted']}")
        print(f"   Confidence: {result['confidence']}")
        print(f"   Modell:     {result['model_version']}")
        print()


if __name__ == "__main__":
    main()
