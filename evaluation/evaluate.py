"""Evaluation V0 des Ticket-Klassifikators.

Schickt die festen Testtickets durch predict_ticket(), vergleicht das
Ergebnis mit der Ground Truth und berechnet Accuracy, Precision, Recall
und Macro-F1. Fehlklassifikationen werden aufgelistet, alle Ergebnisse
landen zusaetzlich in results/evaluation/evaluation_v0.csv.

Das Backend wird nur gelesen, nie veraendert.

Starten aus dem Projekt-Root:
    python3 -m evaluation.evaluate
"""

import csv
from pathlib import Path

from backend.classifier import predict_ticket

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = (
    PROJECT_ROOT / "results" / "evaluation" / "evaluation_v0.csv"
)
FIELDNAMES = [
    "ticket_nr",
    "text",
    "expected",
    "predicted",
    "confidence",
    "model_version",
    "correct",
]

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


def accuracy(results):
    """Anteil richtiger Vorhersagen, Wert zwischen 0.0 und 1.0."""
    if not results:
        return 0.0
    correct = sum(1 for result in results if result["correct"])
    return correct / len(results)


def per_category_scores(results):
    """Precision, Recall und F1 je Kategorie als Dictionary.

    TP: richtig erkannt. FP: falsch in diese Kategorie gesteckt.
    FN: gehoert hierher, wurde aber anders einsortiert.
    """
    categories = {result["expected"] for result in results}
    categories |= {result["predicted"] for result in results}

    scores = {}
    for category in sorted(categories):
        true_positive = sum(
            1 for result in results
            if result["expected"] == category
            and result["predicted"] == category
        )
        false_positive = sum(
            1 for result in results
            if result["predicted"] == category
            and result["expected"] != category
        )
        false_negative = sum(
            1 for result in results
            if result["expected"] == category
            and result["predicted"] != category
        )

        predicted_total = true_positive + false_positive
        expected_total = true_positive + false_negative
        precision = true_positive / predicted_total if predicted_total else 0.0
        recall = true_positive / expected_total if expected_total else 0.0
        if precision + recall:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0

        scores[category] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": expected_total,
        }
    return scores


def macro_f1(results):
    """Mittelwert der F1-Werte aller Kategorien, ungewichtet."""
    scores = per_category_scores(results)
    if not scores:
        return 0.0
    return sum(score["f1"] for score in scores.values()) / len(scores)


def misclassifications(results):
    """Nur die falsch einsortierten Tickets."""
    return [
        {
            "text": result["text"],
            "expected": result["expected"],
            "predicted": result["predicted"],
            "confidence": result["confidence"],
        }
        for result in results if not result["correct"]
    ]


def save_results(results, path=RESULTS_PATH):
    """Schreibt eine Zeile pro Ticket als CSV und gibt den Pfad zurueck.

    Der Zielordner wird angelegt, falls er noch nicht existiert.
    Eine vorhandene Datei wird ueberschrieben, damit immer der
    aktuelle Stand drin steht.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        for number, result in enumerate(results, start=1):
            writer.writerow({
                "ticket_nr": number,
                "text": result["text"],
                "expected": result["expected"],
                "predicted": result["predicted"],
                "confidence": result["confidence"],
                "model_version": result["model_version"],
                "correct": result["correct"],
            })
    return path


def print_metrics(results):
    """Kennzahlen-Block und Fehlklassifikationen ausgeben."""
    correct = sum(1 for result in results if result["correct"])
    share = accuracy(results)

    print("=" * 60)
    print(f"Tickets:   {len(results)}")
    print(f"Richtig:   {correct}")
    print(f"Accuracy:  {share:.2f} ({share * 100:.0f} %)")
    print(f"Macro-F1:  {macro_f1(results):.2f}")
    print()

    print("Pro Kategorie:")
    for category, score in per_category_scores(results).items():
        print(
            f"   {category:<12} "
            f"Precision {score['precision']:.2f}  "
            f"Recall {score['recall']:.2f}  "
            f"F1 {score['f1']:.2f}  "
            f"(n={score['support']})"
        )
    print()

    errors = misclassifications(results)
    if not errors:
        print("Fehlklassifikationen: keine")
        return
    print(f"Fehlklassifikationen: {len(errors)}")
    for error in errors:
        print(f"   Text:       {error['text']}")
        print(f"   Erwartet:   {error['expected']}")
        print(f"   Vorhersage: {error['predicted']}")
        print()


def main():
    results = run_evaluation()
    for number, result in enumerate(results, start=1):
        mark = "OK " if result["correct"] else "FALSCH"
        print(f"{mark} Ticket {number}")
        print(f"   Text:       {result['text']}")
        print(f"   Erwartet:   {result['expected']}")
        print(f"   Vorhersage: {result['predicted']}")
        print(f"   Confidence: {result['confidence']}")
        print(f"   Modell:     {result['model_version']}")
        print()

    print_metrics(results)

    path = save_results(results)
    print()
    print(f"Gespeichert: {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
