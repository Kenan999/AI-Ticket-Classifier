import math
from time import sleep
"""Evaluation des Ticket-Klassifikators am Bitext-Datensatz.

Ground Truth sind die Labels aus data/processed/ - sie sind die
Richtlinie. Die Antwort des Klassifikators wird dafuer in ein Label
uebersetzt. Gemessen werden Accuracy, Precision, Recall und Macro-F1.

Drei Modi, jeder mit fester Stichprobe (Seed 42):
    1. smoke       5 pro Label aus validation.csv - laeuft die Messung?
    2. validation  20 pro Label aus validation.csv - Prompts vergleichen
    3. final       alle Tickets aus test.csv - unabhaengige Abnahme

Jede Kombination aus Modus und Verfahren schreibt in eine eigene CSV
unter results/evaluation/, zum Beispiel smoke_v0.csv.

Das Backend und der Datensatz werden nur gelesen, nie veraendert.

Starten aus dem Projekt-Root:
    python3 -m backend.evaluation.evaluate                        # smoke
    python3 -m backend.evaluation.evaluate --mode validation
    python3 -m backend.evaluation.evaluate --mode final
    python3 -m backend.evaluation.evaluate --provider gemini
"""

import argparse
import csv
import os
from pathlib import Path

import pandas as pd

from backend import keyword_classifier
from backend.keyword_classifier import dataset_label_for, predict_ticket
from backend.data.data_loader import load_dataset
from backend.llms.gemini import (
    DEFAULT_MODEL,
    LLMError,
    classify_with_gemini,
    configured_categories,
)

from backend.llms.openai import DEFAULT_OPENAI_MODEL, classify_with_openai
from backend.evaluation.config import RETRY_BUDGET_SECONDS, REQUEST_INTERVAL_SECONDS
from backend.llms.prompts import DEFAULT_PROMPT_VERSION, PROMPTS, PROVIDER_NAMES, render_prompt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "results" / "evaluation"
ENV_PATH = PROJECT_ROOT / "backend" / ".env"
DATA_DIR = PROJECT_ROOT / "data" / "processed"

# Auswertungs-Modi. "per_label" ist die Zahl der Tickets, die pro
# Datensatz-Label gezogen wird; None bedeutet "alle nehmen".
MODES = {
    "smoke": {
        "label": "Rauchtest",
        "file": "validation.csv",
        "per_label": 5,
    },
    "validation": {
        "label": "Prompt-Validierung",
        "file": "validation.csv",
        "per_label": 20,
    },
    "final": {
        "label": "Endabnahme",
        "file": "test.csv",
        "per_label": None,
    },
}

# Fester Seed, damit jeder Lauf und jeder Teamrechner dieselbe
# Stichprobe zieht.
SAMPLE_SEED = 42

# Verfahren, die gemessen werden koennen. Jedes schreibt in eine eigene
# Datei, damit ein Lauf nie das Ergebnis des anderen ueberschreibt.
BASELINE = "baseline"
GEMINI = "gemini"
LOCAL = "local"
PROVIDERS = {
    BASELINE: {
        "label": "Regeln (V0)",
        "suffix": "v0",
    },
    LOCAL: {"label": "Local Qwen3-4B", "suffix": "local", "provider": LOCAL, "prompt_version": DEFAULT_PROMPT_VERSION},
    GEMINI: {
        "label": "Gemini (Standard)",
        "suffix": "gemini",
        "provider": GEMINI,
        "prompt_version": DEFAULT_PROMPT_VERSION,
    },
    **{
        f"{provider}-{version.lower()}": {
            "label": f"{PROVIDER_NAMES[provider]} (Prompt {version})",
            "suffix": f"{provider}_{version.lower()}",
            "provider": provider,
            "prompt_version": version,
        }
        for version, prompts in PROMPTS.items()
        for provider in prompts
    },
}

# Nur diese Schluessel werden aus backend/.env uebernommen.
ENV_KEYS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "EVALUATION_RETRY_BUDGET_SECONDS",
    "EVALUATION_BATCH_TIMEOUT_SECONDS",
    "EVALUATION_REQUEST_INTERVAL_SECONDS",
    "LLM_TIMEOUT_SECONDS",
    "LLM_CATEGORIES",
)

FIELDNAMES = [
    "ticket_nr",
    "ticket_id",
    "text",
    "expected",
    "predicted",
    "confidence",
    "model_version",
    "prompt_version",
    "correct",
    "error",
]


def load_env(path=ENV_PATH):
    """Liest erlaubte Einstellungen. Prozessvariablen haben Vorrang."""
    values = {}
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in ENV_KEYS:
            values[name] = value.strip().strip('"\'')
    values.update({name: os.environ[name] for name in ENV_KEYS if name in os.environ})
    from backend.llms.config import model_configuration
    for item in model_configuration(values)["llms"]:
        values[item["model_environment_variable"]] = item["model"]
    return values


def mode_number(mode):
    """Platz des Modus in der Reihenfolge: smoke 1, final 3."""
    return list(MODES).index(mode) + 1


def results_path(provider, mode, *, batch=False):
    """Ergebnisdatei: je Verfahren und Modus eine eigene.

    Beispiel: smoke + Regeln -> results/evaluation/01_smoke_v0.csv.
    Die fuehrende Nummer sorgt dafuer, dass die Dateien im Ordner in
    der Reihenfolge der Modi stehen. So ueberschreibt kein Lauf das
    Ergebnis eines anderen.
    """
    suffix = PROVIDERS[provider]["suffix"]
    if batch and provider != BASELINE:
        suffix += "_batch_v1"
    return RESULTS_DIR / f"{mode_number(mode):02d}_{mode}_{suffix}.csv"


def category_to_label():
    """App-Kategorie -> Datensatz-Label, aus dem Backend gelesen.

    Gemessen wird in den Labels des Datensatzes, denn die sind unsere
    Richtlinie. Der Klassifikator antwortet aber in Kategorien, also
    muss seine Antwort uebersetzt werden.

    Die Zuordnung wird nicht hier gepflegt, sondern aus Kenans
    dataset_label_for gelesen.
    """
    mapping = {}
    for category in configured_categories(""):
        label = dataset_label_for(category)
        if label:
            mapping[category] = label
    return mapping


def to_dataset_label(category, mapping=None):
    """Antwort des Klassifikators als Datensatz-Label.

    Ausgaben ohne gueltiges Datensatz-Label bekommen ihren Namen in Klammern. So ist in der Auswertung
    sichtbar, was der Klassifikator wirklich geantwortet hat, und es
    zaehlt zugleich als falsch, weil es kein Label des Datensatzes ist.
    """
    mapping = mapping if mapping is not None else category_to_label()
    return mapping.get(category, f"[{category}]")


def load_mode_tickets(mode, seed=SAMPLE_SEED):
    """Tickets eines Modus aus dem Datensatz ziehen.

    Ground Truth ist das Label des Datensatzes, unveraendert. Es wird
    kein Label weggelassen - alle 9 werden gemessen. Je Label werden
    "per_label" Zeilen gezogen (None = alle). Die CSV bleibt unberuehrt.

    Gibt (tickets, info) zurueck.
    """
    if mode not in MODES:
        raise ValueError(f"Unbekannter Modus: {mode}")

    settings = MODES[mode]
    path = DATA_DIR / settings["file"]
    data = load_dataset(path)

    # Vor dem Ziehen sortieren: so haengt die Stichprobe nicht an der
    # Zeilenreihenfolge der Datei, sondern nur an Datei, Anzahl und Seed.
    data = data.sort_values("ticket_id")

    per_label = settings["per_label"]
    drawn = data
    if per_label is not None:
        parts = []
        for _, group in data.groupby("label", sort=True):
            take = min(per_label, len(group))
            parts.append(group.sample(n=take, random_state=seed))
        drawn = pd.concat(parts).sort_values("ticket_id")

    tickets = [
        {
            "ticket_id": row.ticket_id,
            "text": row.text,
            "expected": row.label,
        }
        for row in drawn.itertuples(index=False)
    ]

    labels = sorted(data["label"].unique())
    reachable = set(category_to_label().values())
    info = {
        "mode": mode,
        "label": settings["label"],
        "file": settings["file"],
        "per_label": per_label,
        "tickets": len(tickets),
        "rows_in_file": len(data),
        "labels": labels,
        "labels_unreachable": [
            name for name in labels if name not in reachable
        ],
        "seed": seed,
    }
    return tickets, info


def classify_ticket(text, provider=BASELINE, env=None):
    """Klassifiziert einen Text mit dem gewaehlten Verfahren.

    Gibt (category, confidence, model_version, error) zurueck.
    Bei einem Provider-Fehler steht in error der Grund und die Kategorie
    ist "FEHLER" - es wird NICHT heimlich auf die Regeln zurueckgefallen,
    sonst waere das Ergebnis eine Mischung aus beiden Verfahren.
    """
    method = PROVIDERS[provider]
    if provider == BASELINE:
        prediction = predict_ticket(text)
        return (prediction.category, prediction.confidence,
                prediction.model_version, "")

    env = env if env is not None else load_env()
    name = method["provider"]
    if name == "local":
        from backend.llms.local import classify_with_local, DEFAULT_LOCAL_MODEL
        try:
            prediction = classify_with_local(text, categories=configured_categories(env.get("LLM_CATEGORIES", "")), model=env.get("LOCAL_LLM_MODEL", DEFAULT_LOCAL_MODEL), timeout=float(env.get("LOCAL_LLM_TIMEOUT_SECONDS", "30")), observation_source="evaluation", prompt_version=method["prompt_version"])
            return prediction.category, prediction.confidence, prediction.model_version, ""
        except (LLMError, ValueError, OverflowError) as exc:
            return "FEHLER", 0.0, "local:nicht erreichbar", type(exc).__name__
    if name == "openai":
        adapter, default_model = classify_with_openai, DEFAULT_OPENAI_MODEL
    else:
        adapter, default_model = classify_with_gemini, DEFAULT_MODEL

    prefix = name.upper()
    key_name = f"{prefix}_API_KEY"
    api_key = env.get(key_name, "").strip()
    if not api_key:
        raise RuntimeError(f"{key_name} fehlt in der Umgebung oder in backend/.env.")

    try:
        categories = configured_categories(env.get("LLM_CATEGORIES", ""))
        prompt_version = method["prompt_version"]
        prompt_options = {"prompt_version": prompt_version}
        if name == GEMINI:
            prompt_options["instructions"] = render_prompt(
                prompt_version, name, categories,
                category_guidance=keyword_classifier.CATEGORY_GUIDANCE,
            )
        prediction = adapter(
            text,
            api_key=api_key,
            categories=categories,
            model=env.get(f"{prefix}_MODEL", default_model),
            timeout=float(env.get("LLM_TIMEOUT_SECONDS", "8")),
            retry_budget=float(env.get("EVALUATION_RETRY_BUDGET_SECONDS", RETRY_BUDGET_SECONDS)),
            **prompt_options,
        )
    except (LLMError, ValueError, OverflowError) as exc:
        # Nie den Tickettext oder den Key mit ausgeben.
        return ("FEHLER", 0.0, f"{name}:nicht erreichbar", str(exc))
    return (prediction.category, prediction.confidence,
            prediction.model_version, "")


def run_evaluation(tickets, provider=BASELINE, *, batch=False, progress=None):
    """Misst alle Tickets mit dem gewaehlten Verfahren.

    Ground Truth ist das Label des Datensatzes, die Antwort des
    Klassifikators wird dafuer in ein Label uebersetzt.
    """
    env = load_env() if provider != BASELINE else {}
    prompt_version = PROVIDERS[provider].get("prompt_version", "")
    mapping = category_to_label()
    interval = float(env.get("EVALUATION_REQUEST_INTERVAL_SECONDS", REQUEST_INTERVAL_SECONDS)) if provider != BASELINE else 0
    if not math.isfinite(interval) or not 0 <= interval <= 600:
        raise ValueError("Evaluation request interval must be between 0 and 600 seconds")
    batched = None
    if batch and provider != BASELINE and PROVIDERS[provider].get("provider") != LOCAL:
        from backend.evaluation.batching import run
        batched = iter(run(tickets, PROVIDERS[provider], env, sleep, progress=progress))
    results = []
    for ticket in tickets:
        if batched is None and results and interval:
            sleep(interval)
        category, confidence, model_version, error = (next(batched) if batched is not None else classify_ticket(
            ticket["text"], provider=provider, env=env,
        ))
        predicted = to_dataset_label(category, mapping)
        results.append({
            "ticket_id": ticket.get("ticket_id", ""),
            "text": ticket["text"],
            "expected": ticket["expected"],
            "predicted": predicted,
            "confidence": confidence,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "correct": predicted == ticket["expected"],
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

    Gewertet werden nur Kategorien, die in der Ground Truth vorkommen.
    Eine Antwort ohne gueltiges Datensatz-Label zaehlt als Fehler
    bei der erwarteten Kategorie und bekommt keine eigene Zeile. Sonst wuerde der
    Macro-F1 ueber erfundene Klassen gemittelt.
    """
    categories = {result["expected"] for result in results}

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


def save_results(results, path):
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
                "ticket_id": result.get("ticket_id", ""),
                "text": result["text"],
                "expected": result["expected"],
                "predicted": result["predicted"],
                "confidence": result["confidence"],
                "model_version": result["model_version"],
                "prompt_version": result.get("prompt_version", ""),
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
    """Liest Verfahren und Modus von der Kommandozeile."""
    parser = argparse.ArgumentParser(
        description="Misst den Ticket-Klassifikator.",
    )
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDERS),
        default=BASELINE,
        help="Regeln, Standard-Gemini oder ein versionierter Gemini-/OpenAI-Prompt",
    )
    parser.add_argument(
        "--mode",
        choices=list(MODES),
        default="smoke",
        help=(
            "Datenquelle. smoke = 5 pro Label (Standard), "
            "validation = 20 pro Label, beide aus validation.csv. "
            "final = alle Tickets aus test.csv"
        ),
    )
    return parser.parse_args(argv)


def print_sample_info(info):
    """Woher die Tickets kommen und was weggelassen wurde."""
    print(f"Datenquelle: {info['file']} ({info['rows_in_file']} Zeilen)")
    if info["per_label"] is None:
        print("Stichprobe:  alle Tickets der messbaren Labels")
    else:
        print(
            f"Stichprobe:  {info['per_label']} pro Label, "
            f"Seed {info['seed']}"
        )
    print(f"Tickets:     {info['tickets']}")
    print(
        f"Labels:      {len(info['labels'])} - "
        f"{', '.join(info['labels'])}"
    )
    if info["labels_unreachable"]:
        print(
            "Unerreichbar: "
            f"{', '.join(info['labels_unreachable'])} - der "
            "Klassifikator hat keine Kategorie dafuer und kann sie "
            "nie treffen"
        )
    print()


def main(argv=None):
    args = parse_args(argv)
    provider, mode = args.provider, args.mode
    print(f"Verfahren: {PROVIDERS[provider]['label']}")
    print(f"Modus:     {MODES[mode]['label']} ({mode})")
    print()

    tickets, info = load_mode_tickets(mode)
    print_sample_info(info)

    results = run_evaluation(tickets=tickets, provider=provider, batch=True)

    # Einzelne Tickets nur bei kleinen Laeufen ausgeben, sonst
    # verschwinden die Kennzahlen in hunderten Zeilen.
    if len(results) <= 10:
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

    path = save_results(results, results_path(provider, mode, batch=True))
    print()
    print(f"Gespeichert: {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
