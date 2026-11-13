"""Evaluation des Ticket-Klassifikators an festen Testtickets.

Misst wahlweise den Regel-Klassifikator oder Gemini mit dem bestehenden
Prompt aus backend/llm_classifier.py, vergleicht das Ergebnis mit der
Ground Truth und berechnet Accuracy, Precision, Recall und Macro-F1.
Jedes Verfahren schreibt in eine eigene CSV unter results/evaluation/.

Das Backend wird nur gelesen, nie veraendert.

Starten aus dem Projekt-Root:
    python3 -m evaluation.evaluate                      # Regeln
    python3 -m evaluation.evaluate --provider gemini    # Gemini
"""

import argparse
import csv
from pathlib import Path

from backend.classifier import predict_ticket
from backend.llm_classifier import (
    DEFAULT_MODEL,
    LLMError,
    classify_with_gemini,
    configured_categories,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "evaluation"
ENV_PATH = PROJECT_ROOT / "backend" / ".env"

# Verfahren, die gemessen werden koennen. Jedes schreibt in eine eigene
# Datei, damit ein Lauf nie das Ergebnis des anderen ueberschreibt.
BASELINE = "baseline"
GEMINI = "gemini"
PROVIDERS = {
    BASELINE: {
        "label": "Regeln (V0)",
        "file": "evaluation_v0.csv",
    },
    GEMINI: {
        "label": "Gemini (bestehender Prompt)",
        "file": "evaluation_gemini.csv",
    },
}

# Nur diese Schluessel werden aus backend/.env uebernommen.
ENV_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_CATEGORIES",
)

RESULTS_PATH = RESULTS_DIR / PROVIDERS[BASELINE]["file"]
FIELDNAMES = [
    "ticket_nr",
    "text",
    "expected",
    "predicted",
    "confidence",
    "model_version",
    "correct",
    "error",
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


def load_env(path=ENV_PATH):
    """Liest die erlaubten Schluessel aus backend/.env.

    Bewusst ohne Import von backend/app.py: der wuerde beim Import
    Flask starten und eine SQLite-Datei anlegen.
    """
    values = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in ENV_KEYS:
            values[name] = value.strip().strip('"\'')
    return values


def results_path(provider=BASELINE):
    """Ergebnisdatei des jeweiligen Verfahrens."""
    return RESULTS_DIR / PROVIDERS[provider]["file"]


def classify_ticket(text, provider=BASELINE, env=None):
    """Klassifiziert einen Text mit dem gewaehlten Verfahren.

    Gibt (category, confidence, model_version, error) zurueck.
    Bei einem Gemini-Fehler steht in error der Grund und die Kategorie
    ist "FEHLER" - es wird NICHT heimlich auf die Regeln zurueckgefallen,
    sonst waere das Ergebnis eine Mischung aus beiden Verfahren.
    """
    if provider != GEMINI:
        prediction = predict_ticket(text)
        return (prediction.category, prediction.confidence,
                prediction.model_version, "")

    env = env if env is not None else load_env()
    api_key = env.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY fehlt in backend/.env - "
            "ohne Key kann Gemini nicht gemessen werden."
        )
    try:
        prediction = classify_with_gemini(
            text,
            api_key=api_key,
            categories=configured_categories(
                env.get("LLM_CATEGORIES", "")
            ),
            model=env.get("GEMINI_MODEL", DEFAULT_MODEL),
            timeout=float(env.get("LLM_TIMEOUT_SECONDS", "8")),
        )
    except (LLMError, ValueError, OverflowError) as exc:
        # Nie den Tickettext oder den Key mit ausgeben.
        return ("FEHLER", 0.0, "gemini:nicht erreichbar", str(exc))
    return (prediction.category, prediction.confidence,
            prediction.model_version, "")


def run_evaluation(tickets=TEST_TICKETS, provider=BASELINE):
    """Misst alle Tickets mit dem gewaehlten Verfahren."""
    env = load_env() if provider == GEMINI else {}
    results = []
    for ticket in tickets:
        category, confidence, model_version, error = classify_ticket(
            ticket["text"], provider=provider, env=env,
        )
        results.append({
            "text": ticket["text"],
            "expected": ticket["expected"],
            "predicted": category,
            "confidence": confidence,
            "model_version": model_version,
            "correct": category == ticket["expected"],
            "error": error,
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
                "error": result.get("error", ""),
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


def parse_args(argv=None):
    """Liest das gewuenschte Verfahren von der Kommandozeile."""
    parser = argparse.ArgumentParser(
        description="Misst den Ticket-Klassifikator an festen Tickets.",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDERS),
        default=BASELINE,
        help="baseline = Regeln (Standard), gemini = Gemini",
    )
    return parser.parse_args(argv)


def main(argv=None):
    provider = parse_args(argv).provider
    print(f"Verfahren: {PROVIDERS[provider]['label']}")
    print()

    results = run_evaluation(provider=provider)
    for number, result in enumerate(results, start=1):
        mark = "OK " if result["correct"] else "FALSCH"
        print(f"{mark} Ticket {number}")
        print(f"   Text:       {result['text']}")
        print(f"   Erwartet:   {result['expected']}")
        print(f"   Vorhersage: {result['predicted']}")
        print(f"   Confidence: {result['confidence']}")
        print(f"   Modell:     {result['model_version']}")
        if result["error"]:
            print(f"   Fehler:     {result['error']}")
        print()

    print_metrics(results)

    path = save_results(results, results_path(provider))
    print()
    print(f"Gespeichert: {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
