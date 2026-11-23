"""Streamlit-Dashboard fuer die Evaluation.

Zeigt Accuracy, Macro-F1, die Werte je Label und die
Fehlklassifikationen - fuer den links gewaehlten Modus (Rauchtest,
Prompt-Validierung, Endabnahme) und das gewaehlte Verfahren. Gelesen
wird die passende Datei aus results/evaluation/, zum Beispiel
01_smoke_v0.csv.

Die Kennzahlen werden mit den Funktionen aus evaluation/evaluate.py
berechnet, damit Dashboard und Konsole immer dieselben Werte zeigen.

Starten aus dem Projekt-Root:
    (cd backend && python -m streamlit run evaluation/dashboard.py)
"""

import difflib
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# Streamlit startet diese Datei direkt, deshalb kennt Python den
# Projekt-Root nicht automatisch. Ohne diese Zeile schlaegt der Import
# von evaluation.evaluate fehl.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.evaluation.evaluate import (  # noqa: E402
    BASELINE,
    GEMINI,
    MODES,
    PROVIDERS,
    SAMPLE_SEED,
    accuracy,
    load_mode_tickets,
    macro_f1,
    misclassifications,
    mode_number,
    per_category_scores,
    results_path,
    run_evaluation,
    save_results,
)


# Farben aus der geprueften Standardpalette. Reihenfolge ist fest:
# Precision blau, Recall orange, F1 aqua.
COLOR_PRECISION = "#2a78d6"
COLOR_RECALL = "#eb6834"
COLOR_F1 = "#1baf7a"

# Versionsvergleich: Blau und Orange statt Blau und Violett, weil
# Blau/Violett im Farbtest fuer Rot-Gruen-Schwaeche durchfaellt.
COLOR_ACCURACY = "#2a78d6"
COLOR_MACRO_F1 = "#eb6834"

# Zielwerte. Vorlaeufig gesetzt - hier aendern, wenn das Team andere
# Ziele beschliesst. Sie werden als Linie im Diagramm und als Abstand
# auf den KPI-Karten angezeigt.
TARGET_ACCURACY = 0.90
TARGET_MACRO_F1 = 0.85

# Die Tabelle zeigt nur gemessene Kennzahlen. Versionierte Methoden
# werden aus derselben Liste wie die Auswahl in der Seitenleiste erzeugt.
VERSIONS = [
    {
        "key": "V0",
        "short": "V0 · Regeln",
        "provider": BASELINE,
        "tint": "#eaf2fc",
        "ink": "#1b5fae",
        "approach": "Regeln, kein LLM",
        "prompt": (
            "Kein Prompt. Gezählte Stichwörter mit festen Punktwerten "
            "in backend/keyword_classifier.py."
        ),
    },
    *(
        {
            "key": key,
            "short": method["label"],
            "provider": key,
            "tint": "#fdf0ea" if method["provider"] == GEMINI else "#f0eefc",
            "ink": "#a8451c" if method["provider"] == GEMINI else "#5541a6",
            "approach": "Versionierter System-Prompt",
            "prompt": "Prompt-Text in backend/llms/prompts.py.",
        }
        for key, method in PROVIDERS.items()
        if key not in {BASELINE, GEMINI}
    ),
]

def configured_versions():
    from backend.llms.config import model_configuration
    from backend.evaluation.evaluate import load_env
    versions = [VERSIONS[0]]
    for item in model_configuration(load_env())["llms"]:
        for prompt in ("V1", "V2", "V3"):
            key = item["id"] + "-" + prompt.lower()
            versions.append({"key": key, "provider": key,
                "model": item["model"], "short": item["model"] + " · " + prompt,
                "tint": "#fdf0ea" if item["id"] == "gemini" else "#f0eefc",
                "ink": "#a8451c" if item["id"] == "gemini" else "#5541a6",
                "approach": "Versionierter System-Prompt", "prompt": ""})
    return versions


TABLE_STYLE = """
<style>
.ev-table-scroll { width: 100%; overflow-x: auto; padding-bottom: 0.7rem; }
.ev-table th.ev-group { border-left: 8px solid var(--background-color, Canvas); padding: 0.8rem; overflow-wrap: anywhere; }
.ev-table thead tr:nth-child(2) th:nth-child(3n+2),
.ev-table tbody tr:not(.ev-summary) td:nth-child(3n+2),
.ev-table .ev-summary td:not(:first-child) { border-left: 8px solid var(--background-color, Canvas); }
.ev-table tbody tr:nth-child(even):not(.ev-summary) { background: rgba(128,128,128,0.06); }
.ev-table tbody tr:hover { background: rgba(128,128,128,0.12); }
.ev-table .ev-name, .ev-table .ev-corner { position: sticky; left: 0; z-index: 1; background: var(--background-color, Canvas); }
.ev-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.86rem;
    font-variant-numeric: tabular-nums;
}
.ev-table th, .ev-table td {
    padding: 0.42rem 0.5rem;
    text-align: center;
    border-bottom: 1px solid rgba(128, 128, 128, 0.18);
}
.ev-group {
    font-weight: 600;
    border-radius: 6px 6px 0 0;
    letter-spacing: 0.01em;
}
.ev-table .ev-sub { font-weight: 600; opacity: 1; color: #293548; font-size: 0.78rem; }
.ev-corner { background: transparent; }
.ev-name { text-align: left; font-weight: 500; white-space: nowrap; }
.ev-value { opacity: 0.85; }
.ev-strong { font-weight: 700; opacity: 1; }
.ev-empty { opacity: 0.35; }
.ev-table .ev-total { font-weight: 700; color: #293548; opacity: 1; }
.ev-summary td { border-top: 2px solid rgba(128, 128, 128, 0.35); }
</style>
"""

# Statusfarben, nur mit Text daneben verwenden, nie Farbe allein.
COLOR_GOOD = "#0ca30c"
COLOR_WARNING = "#fab219"
COLOR_CRITICAL = "#d03b3b"

HELP_ACCURACY = (
    "Anteil richtig einsortierter Tickets. "
    "Wert zwischen 0 und 1, Bestwert 1.00."
)
HELP_MACRO_F1 = (
    "Mittelwert der F1-Werte aller Kategorien. Strenger als Accuracy, "
    "weil kleine Kategorien genauso zaehlen wie grosse."
)
HELP_TICKETS = "Anzahl der ausgewerteten Test-Tickets."
HELP_ERRORS = (
    "Tickets, bei denen die Vorhersage nicht zur Ground Truth passt."
)

BACKLOG = """
Bewusst noch offen – hier gesammelt, damit nichts verloren geht:

- **Automatisierungsquote** – Anteil der Tickets, die der Klassifikator
  allein erledigen kann, gegenüber denen, die an einen Menschen gehen.
  Das Backend hat dafür schon eine Schwelle (`REVIEW_THRESHOLD = 0.75`).
  Das ist die eigentliche Management-Kennzahl.
- **Klartext-Fazit** – ein Satz statt einer Tabelle, zum Beispiel
  "V3 ist besser als V2, Hauptschwäche bleibt REFUND".
- **Kosten pro Durchlauf** – bei Gemini: wie viel kostet eine Messung?
- **Getrennte Ansichten** – eine kompakte Management-Sicht und eine
  ausführliche Entwickler-Sicht auf derselben Seite.
"""

METRIC_EXPLANATIONS = """
- **Accuracy** – Anteil richtig einsortierter Tickets. 1.00 = alle richtig.
- **Precision** – Wenn der Klassifikator "Shipping" sagt: wie oft stimmt
  das wirklich? Niedrig heisst: er steckt zu viel in diese Kategorie.
- **Recall** – Von allen echten Shipping-Tickets: wie viele hat er
  gefunden? Niedrig heisst: er übersieht Tickets dieser Kategorie.
- **F1** – Mischwert aus Precision und Recall. Bestwert 1.00.
- **Macro-F1** – Mittelwert der F1-Werte aller Kategorien.

Alle Werte liegen zwischen 0 und 1. Prozent wäre bei F1 irreführend,
weil es kein "x von 100 richtig" bedeutet.
"""


def last_run(path):
    """Zeitpunkt des letzten Laufs, aus dem Dateidatum der CSV."""
    if not path.is_file():
        return None
    stamp = datetime.fromtimestamp(path.stat().st_mtime)
    return stamp.strftime("%d.%m.%Y um %H:%M Uhr")


def load_results(path):
    """Liest die CSV und baut die Ergebnisliste wieder auf.

    "correct" wird neu aus expected und predicted bestimmt, damit das
    Dashboard nicht davon abhaengt, wie die CSV True/False einliest.
    """
    frame = pd.read_csv(path)
    results = []
    for row in frame.to_dict(orient="records"):
        error = row.get("error")
        results.append({
            "text": row["text"],
            "expected": row["expected"],
            "predicted": row["predicted"],
            "confidence": row["confidence"],
            "model_version": row["model_version"],
            "prompt_version": row.get("prompt_version"),
            "correct": row["expected"] == row["predicted"],
            "error": error if isinstance(error, str) else "",
        })
    return results


@st.cache_data(show_spinner=False)
def rows_per_label(mode):
    """Wie viele Tickets ein Modus je Kategorie misst.

    Bei "alle" steht die Zahl nicht in MODES, sie wird aus der Datei
    gezaehlt. So stimmt sie auch, wenn sich der Datensatz aendert.
    """
    per_label = MODES[mode]["per_label"]
    if per_label is not None:
        return per_label
    _, info = load_mode_tickets(mode)
    labels = len(info["labels"]) or 1
    return info["tickets"] // labels


def mode_label(mode):
    """Erste Zeile eines Modus: Nummer, Name und Umfang."""
    settings = MODES[mode]
    amount = rows_per_label(mode)
    return (
        f"{mode_number(mode)}. {settings['label']} "
        f"({amount} pro Kategorie)"
    )


def mode_caption(mode):
    """Zweite Zeile: Quelldatei, klein, grau und kursiv."""
    return f"*{MODES[mode]['file']}*"


def missing_prompt_message(provider):
    from backend.llms.prompts import PROMPTS
    if provider == BASELINE:
        return None
    method = PROVIDERS[provider]
    version = method["prompt_version"]
    template = PROMPTS.get(version, {}).get(method["provider"], "")
    if template.strip():
        return None
    return f"Bitte zuerst den Prompt für {version} in backend/llms/prompts.py eintragen. Danach kann diese Version ausgewertet werden."


def render_sidebar():
    """Choose test dataset, prompt version, then classification method."""
    with st.sidebar:
        st.header("Steuerung")
        mode = st.radio(
            "1. Test und Datensatz", options=list(MODES),
            format_func=lambda key: {
                "smoke": "Smoke-Test · 45 Tickets",
                "validation": "Prompt-Validierung · 180 Tickets",
                "final": "Endabnahme · 1.800 Tickets",
            }[key],
        )
        dataset_error = None
        try:
            _, info = load_mode_tickets(mode)
            st.info(f"Dieser Datensatz wird verwendet: {MODES[mode]['file']} — {info['tickets']} Tickets.")
            st.caption("Feste Stichprobe für vergleichbare Ergebnisse." if mode != "final" else "Unabhängige Testdaten für die Endabnahme.")
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            dataset_error = str(exc)
            st.error(dataset_error)
        prompt_controls = st.container()
        from backend.evaluation.evaluate import load_env, DEFAULT_MODEL, DEFAULT_OPENAI_MODEL
        model_env = load_env()
        from backend.llms.config import model_configuration
        active_models = {item["id"]: item["model"]
                         for item in model_configuration(model_env)["llms"]}
        engine = st.selectbox(
            "3. Modell / Verfahren", options=[BASELINE, *active_models],
            format_func=lambda key: "Lokale Regeln (kein LLM)" if key == BASELINE else active_models[key],
            help="Lokale Regeln brauchen keinen Prompt. Gemini und OpenAI benötigen einen API-Key.",
        )
        with prompt_controls:
            version = st.selectbox(
                "2. Prompt-Version", options=["V1", "V2", "V3"],
                disabled=engine == BASELINE,
                help="Versionen ohne konfigurierten Prompt bleiben gesperrt.",
            )
            if engine == BASELINE:
                st.caption("Nicht erforderlich: Lokale Regeln verwenden keinen Prompt.")
        provider = BASELINE if engine == BASELINE else f"{engine}-{version.lower()}"
        if engine != BASELINE:
            st.info(f"Modell für neue Tests: {active_models[engine]}")
        st.checkbox("Tickets gemeinsam senden (Batch)", value=True,
                    key="batch_evaluation", disabled=engine in {BASELINE, "local"})
        if engine not in {BASELINE, "local"} and st.session_state.get("batch_evaluation", True):
            st.caption("Batch-Limits: evaluation/config.py. Automatische Gruppengröße nach Textlänge und Token-Budget; kein festes 20-Ticket-Limit. Alte Einzel-Ergebnisse: Batch ausschalten.")
        supported = provider in PROVIDERS
        prompt_missing = (missing_prompt_message(provider) if supported else
                          "Dieses Modell ist konfiguriert, hat aber noch keinen Evaluation-Adapter. Keine Ergebnisse verfügbar.")
        if prompt_missing:
            st.info(prompt_missing)

        if st.button("Evaluation neu ausführen", width="stretch", disabled=bool(prompt_missing or dataset_error)):
            try:
                with st.spinner("Messung läuft …"):
                    tickets, _ = load_mode_tickets(mode)
                    progress_bar = st.progress(0, text="Evaluation: 0 %")
                    request_status = st.empty()
                    limit_status = st.empty()
                    def show_progress(state):
                        percent = state["completed"] / state["total"] if state["total"] else 1.0
                        progress_bar.progress(percent, text=f"Evaluation: {percent:.0%} · {state['completed']}/{state['total']} Tickets verarbeitet")
                        request_status.caption(f"{state['requests']} HTTP-Anfragen · {state['retries']} Wiederholungen · {state['batches']} geplante Batches · {state['errors']} fehlgeschlagene Tickets · {state.get('metadata_requests', 0)} Metadaten-Anfragen")
                        limit_status.caption(f"Limits: {state.get('limits_source', 'configured')}. Kontingentinformationen nur soweit der Provider sie liefert.")
                        st.session_state["last_batch_progress"] = dict(state, provider=provider, mode=mode)
                    measured = run_evaluation(progress=show_progress,batch=st.session_state.get("batch_evaluation", True) and provider.split("-")[0] != "local",
                        tickets=tickets, provider=provider,
                    )
                    save_results(
                        measured, results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True) and provider.split("-")[0] != "local"),
                    )
            except (RuntimeError, FileNotFoundError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.success("Neu berechnet und gespeichert.")
                st.rerun()

        last_run = st.session_state.get("last_batch_progress")
        if (last_run and last_run["provider"] == provider and last_run["mode"] == mode
                and st.session_state.get("batch_evaluation", True)):
            percent = last_run["completed"] / last_run["total"] if last_run["total"] else 1.0
            st.progress(percent, text=f"Letzter Batch-Lauf: {percent:.0%} verarbeitet")
            st.caption(f"{last_run['requests']} HTTP-Anfragen, davon {last_run['retries']} Wiederholungen. {last_run['errors']} fehlgeschlagene Tickets. Fortschritt ist nicht Accuracy.")
        st.divider()
        st.caption("Ergebnisdatei")
        if supported:
            st.code(results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True) and provider.split("-")[0] != "local").name, language=None)
        return provider, mode, prompt_missing


def render_header(results, provider, path, mode=None):
    """Titel, gewaehltes Verfahren und Hinweis zur Datenquelle."""
    title, badge = st.columns([4, 2], vertical_alignment="center")
    title.title("Ticket-Klassifikator – Evaluation")
    models = sorted({display_model(row.get("model_version")) for row in results})
    badge.success(" · ".join(models))
    st.caption("Prompt: " + str(PROVIDERS[provider].get("prompt_version", "—")))
    stamp = last_run(path)
    if stamp:
        st.caption(
            f"Letzte Messung: {stamp}"
        )
    render_data_note(results, mode)


def render_data_note(results, mode):
    """Hinweis, woher die gemessenen Tickets kommen.

    Je Modus ein anderer Text, dazu die Quelldatei, der Umfang und die
    Labels, die der Klassifikator gar nicht treffen kann.
    """
    settings = MODES[mode]
    try:
        _, info = load_mode_tickets(mode)
    except (FileNotFoundError, ValueError) as exc:
        st.error(str(exc))
        return

    source = f"`{info['file']}` ({info['rows_in_file']} Zeilen)"
    if settings["per_label"] is None:
        drawn = "alle Tickets der messbaren Labels"
    else:
        drawn = (
            f"{settings['per_label']} pro Label, Seed {info['seed']} – "
            "jeder Lauf zieht dieselbe Stichprobe"
        )

    labels = f"alle {len(info['labels'])} Labels des Datensatzes"
    if mode == "smoke":
        st.info(
            f"**Rauchtest mit {len(results)} echten Tickets** aus "
            f"{source}, {labels}. {drawn.capitalize()}. Gedacht zum "
            "Prüfen, ob die Messung läuft – zu klein für belastbare "
            "Aussagen.",
            icon="🔎",
        )
    elif mode == "final":
        st.success(
            f"**Endabnahme mit {len(results)} Tickets** aus {source}, "
            f"{labels} – unabhängige Testdaten. "
            f"{drawn.capitalize()}.",
            icon="✅",
        )
    else:
        st.info(
            f"**{len(results)} echte Tickets** aus {source}, "
            f"{labels}. {drawn}.",
            icon="📊",
        )

    if info["labels_unreachable"]:
        st.warning(
            "**Unerreichbar: "
            f"{', '.join(info['labels_unreachable'])}** – für diese "
            "Labels hat der Klassifikator keine Kategorie, er kann sie "
            "also nie treffen. Sie werden mitgemessen und zählen als "
            "falsch. Das drückt Accuracy und Macro-F1 und ist genau "
            "die Lücke, die Kenans Ticket schließt.",
            icon="⚠️",
        )


def render_kpis(results):
    """Vier KPI-Karten mit Erklaerung als Tooltip."""
    correct = sum(1 for result in results if result["correct"])
    errors = len(results) - correct
    share = accuracy(results)
    macro = macro_f1(results)

    first, second, third, fourth = st.columns(4)
    with first:
        st.metric("Tickets", len(results), help=HELP_TICKETS)
    with second:
        st.metric(
            "Accuracy",
            f"{share:.2f}",
            delta=f"{share - TARGET_ACCURACY:+.2f} ggü. Ziel",
            help=HELP_ACCURACY,
        )
        st.progress(share)
        st.caption(f"Ziel: {TARGET_ACCURACY:.2f}")
    with third:
        st.metric(
            "Macro-F1",
            f"{macro:.2f}",
            delta=f"{macro - TARGET_MACRO_F1:+.2f} ggü. Ziel",
            help=HELP_MACRO_F1,
        )
        st.progress(macro)
        st.caption(f"Ziel: {TARGET_MACRO_F1:.2f}")
    with fourth:
        st.metric(
            "Fehlklassifikationen",
            errors,
            delta=None if errors == 0 else f"-{errors}",
            delta_color="inverse",
            help=HELP_ERRORS,
        )

    st.caption(f"{correct} von {len(results)} Tickets richtig einsortiert.")

    provider_errors = sum(bool(result.get("error")) for result in results)
    if provider_errors:
        st.warning(
            f"{provider_errors} Tickets ohne Klassifikation wegen Providerfehlern. "
            "Diese Tickets zählen in den Kennzahlen als falsch."
        )

    with st.expander("Was bedeuten diese Kennzahlen?"):
        st.markdown(METRIC_EXPLANATIONS)


def for_display(rows):
    """Tabelle fuer die Anzeige aufbereiten.

    Antworten, die es im Datensatz nicht gibt, stehen in eckigen
    Klammern. Die sollen im Dashboard nicht auftauchen, deshalb wird
    die Zelle geleert. Die Zeile bleibt stehen und zaehlt weiter als
    falsch - nur der erfundene Name verschwindet.
    """
    cleaned = []
    for row in rows:
        row = dict(row)
        value = str(row.get("predicted", ""))
        if value.startswith("["):
            row["predicted"] = "–"
        cleaned.append(row)
    return pd.DataFrame(cleaned)


MATRIX_RAMPS = {
    "correct": ((232, 245, 236), (34, 120, 74)),
    "wrong": ((253, 235, 235), (178, 45, 45)),
}
MATRIX_TEXT = "#111827"
MATRIX_FAILED_TEXT = "rgb(178, 45, 45)"
FAILED_COLUMN = "[FEHLER]"


def matrix_color(kind, share):
    """CSS fuer eine Zelle, Staerke nach Anteil zwischen 0 und 1.

    Der Startwert 0.15 sorgt dafuer, dass auch ein einzelnes Ticket
    sichtbar bleibt. Die Textfarbe wird mitgesetzt, damit die Zahl in
    hellem wie dunklem Streamlit-Design lesbar bleibt.
    """
    light, strong = MATRIX_RAMPS[kind]
    weight = 0.15 + 0.85 * min(max(share, 0.0), 1.0)
    red, green, blue = (
        round(start + (end - start) * weight)
        for start, end in zip(light, strong)
    )
    return (f"background-color: rgb({red}, {green}, {blue}); "
            f"color: {MATRIX_TEXT};")


def matrix_styles(frame):
    """Hintergrundfarben fuer die Confusion-Matrix.

    Gruen auf der Diagonale (richtig), rot daneben (verwechselt),
    roter Text ohne Hintergrund in der Spalte [FEHLER] - eine
    gescheiterte Anfrage ist keine Fehlklassifikation. Nullen bleiben
    ohne Farbe. Die Staerke ist der
    Anteil an der Zeilensumme, damit die Matrix in allen drei Modi
    gleich aussieht. Zahlen und Aufbau der Tabelle bleiben unberuehrt.
    """
    styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
    for label in frame.index:
        total = frame.loc[label].sum()
        if not total:
            continue
        for column in frame.columns:
            count = frame.loc[label, column]
            if not count:
                continue
            if column == FAILED_COLUMN:
                styles.loc[label, column] = (
                    f"color: {MATRIX_FAILED_TEXT}; font-weight: 600;"
                )
                continue
            kind = "correct" if column == label else "wrong"
            styles.loc[label, column] = matrix_color(
                kind, count / total,
            )
    return styles


def confusion_matrix(results):
    """Count the tickets for every pair of true label and predicted label.

    Rows are the true labels, columns are the model's answers. The labels
    come first in sorted order. Answers that are not a label (for example
    "[FEHLER]" for a failed request) get a column of their own after them.
    """
    labels = sorted({row["expected"] for row in results})
    frame = pd.DataFrame(results)
    others = sorted(set(frame["predicted"]) - set(labels))
    counts = pd.crosstab(frame["expected"], frame["predicted"])
    return counts.reindex(index=labels, columns=labels + others, fill_value=0)


def version_metrics(version, mode=None):
    """Kennzahlen einer Version fuer die gewaehlte Datenquelle.

    Der Pfad wird hier aus Verfahren und Modus gebildet, damit die
    Tabelle immer dieselbe Datenquelle zeigt wie der Rest der Seite.
    Eine Version ohne Ergebnisdatei liefert bewusst None. Es werden
    niemals Platzhalterzahlen erfunden.
    """
    provider = version["provider"]
    if provider not in PROVIDERS or missing_prompt_message(provider):
        return None
    path = results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True) and provider.split("-")[0] != "local")
    if not path.is_file():
        return None
    results = load_results(path)
    if not results or all(result.get("error") for result in results):
        return None
    return {
        "results": results,
        "scores": per_category_scores(results),
        "accuracy": accuracy(results),
        "macro_f1": macro_f1(results),
    }


def display_model(value):
    """Remove evaluation metadata from a recorded model identifier for display only."""
    value = str(value or "Unbekannt")
    parts = value.split(":")
    if len(parts) > 1 and parts[0] in {"gemini", "openai", "local"}:
        value = parts[1]
    return value


def model_label(provider, results=None):
    if provider == BASELINE:
        return "Lokale Regeln (kein LLM)"
    if provider not in PROVIDERS:
        entry = next(v for v in configured_versions() if v["provider"] == provider)
        return entry["short"] + " · nicht unterstützt"
    method = PROVIDERS[provider]
    if results:
        models = sorted({display_model(row.get("model_version")) for row in results})
        name = ", ".join(models)
    else:
        from backend.evaluation.evaluate import load_env, DEFAULT_MODEL, DEFAULT_OPENAI_MODEL
        engine = method["provider"]
        from backend.llms.local import DEFAULT_LOCAL_MODEL
        default = DEFAULT_LOCAL_MODEL if engine == "local" else (DEFAULT_MODEL if engine == "gemini" else DEFAULT_OPENAI_MODEL)
        name = load_env().get("LOCAL_LLM_MODEL" if engine == "local" else engine.upper() + "_MODEL", default)

    return name + " · " + str(method.get("prompt_version", "V1"))


def comparison_label(version, measured):
    data = measured.get(version["key"])
    return model_label(version["provider"], data["results"] if data else None)


def version_table_html(measured, versions=None):
    """Baut die Vergleichstabelle als HTML.

    Zeilen sind Kategorien, je Version eine Spaltengruppe mit
    Precision, Recall und F1. Unten Macro-F1 und Accuracy.
    """
    versions = VERSIONS if versions is None else versions
    categories = []
    for data in measured.values():
        for category in data["scores"]:
            if category not in categories:
                categories.append(category)
    if not categories:
        from backend.keyword_classifier import DATASET_CATEGORIES
        categories = list(DATASET_CATEGORIES)
    categories.sort()

    head_top = ['<th class="ev-corner">Kategorie</th>']
    head_sub = []
    for version in versions:
        key = version["key"]
        head_top.append(
            f'<th colspan="3" class="ev-group" '
            f'style="background:{version["tint"]};'
            f'color:{version["ink"]}">{escape(comparison_label(version, measured))}</th>'
        )
        for metric in ("P", "R", "F1"):
            head_sub.append(
                f'<th class="ev-sub" '
                f'style="background:{version["tint"]}">{metric}</th>'
            )

    body = []
    for category in categories:
        cells = [f'<td class="ev-name">{escape(category)}</td>']
        for version in versions:
            data = measured.get(version["key"])
            score = data["scores"].get(category) if data else None
            for key in ("precision", "recall", "f1"):
                if score is None:
                    cells.append('<td class="ev-empty">–</td>')
                else:
                    strong = ' ev-strong' if key == "f1" else ''
                    cells.append(
                        f'<td class="ev-value{strong}">'
                        f'{score[key]:.2f}</td>'
                    )
        body.append("<tr>" + "".join(cells) + "</tr>")

    for label, key, fmt in (
        ("Macro-F1", "macro_f1", "{:.2f}"),
        ("Accuracy", "accuracy", "{:.0%}"),
    ):
        cells = [f'<td class="ev-name ev-strong">{label}</td>']
        for version in versions:
            data = measured.get(version["key"])
            if data is None:
                cells.append('<td colspan="3" class="ev-empty">–</td>')
            else:
                cells.append(
                    f'<td colspan="3" class="ev-total" '
                    f'style="background:{version["tint"]}">'
                    f'{fmt.format(data[key])}</td>'
                )
        body.append('<tr class="ev-summary">' + "".join(cells) + "</tr>")

    # Feste Spaltenbreiten, damit jede Version gleich breit ist -
    # unabhaengig davon, ob sie Zahlen oder nur Striche enthaelt.
    value_columns = len(versions) * 3
    colgroup = (
        '<colgroup><col style="width:190px">'
        + '<col style="width:82px">' * value_columns
        + "</colgroup>"
    )

    return (
        TABLE_STYLE
        + '<div class="ev-table-scroll" role="region" aria-label="Modellvergleich" tabindex="0">'
        + f'<table class="ev-table" style="min-width:{190 + 246 * len(versions)}px">'
        + colgroup
        + "<thead><tr>"
        + "".join(head_top)
        + '</tr><tr><th class="ev-corner"></th>'
        + "".join(head_sub)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def version_chart(measured):
    """Balkendiagramm Accuracy und Macro-F1 je Version."""
    # Alle Versionen kommen auf die Achse, auch die ungemessenen.
    # Sie bekommen keinen Wert, damit sichtbar ist: da kommt noch was.
    rows = []
    pending = []
    for version in VERSIONS:
        data = measured.get(version["key"])
        if data is None:
            pending.append({"Version": comparison_label(version, measured), "Hinweis": "offen"})
            rows.append({
                "Version": comparison_label(version, measured),
                "Kennzahl": "Accuracy",
                "Wert": None,
            })
            rows.append({
                "Version": comparison_label(version, measured),
                "Kennzahl": "Macro-F1",
                "Wert": None,
            })
            continue
        rows.append({
            "Version": comparison_label(version, measured),
            "Kennzahl": "Accuracy",
            "Wert": round(data["accuracy"], 2),
        })
        rows.append({
            "Version": comparison_label(version, measured),
            "Kennzahl": "Macro-F1",
            "Wert": round(data["macro_f1"], 2),
        })
    frame = pd.DataFrame(rows)
    axis_order = [comparison_label(version, measured) for version in VERSIONS]
    order = ["Accuracy", "Macro-F1"]
    base = alt.Chart(frame).encode(
        x=alt.X(
            "Version:N",
            title=None,
            sort=axis_order,
            scale=alt.Scale(domain=axis_order),
            axis=alt.Axis(labelAngle=0, labelFontSize=12),
        ),
        xOffset=alt.XOffset("Kennzahl:N", sort=order),
        y=alt.Y(
            "Wert:Q",
            title=None,
            scale=alt.Scale(domain=[0, 1]),
            axis=alt.Axis(values=[0, 0.2, 0.4, 0.6, 0.8, 1.0]),
        ),
        tooltip=[
            alt.Tooltip("Version:N"),
            alt.Tooltip("Kennzahl:N"),
            alt.Tooltip("Wert:Q", format=".2f"),
        ],
    )
    bars = base.mark_bar(
        size=46,
        cornerRadiusTopLeft=4,
        cornerRadiusTopRight=4,
    ).encode(
        color=alt.Color(
            "Kennzahl:N",
            sort=order,
            scale=alt.Scale(
                domain=order,
                range=[COLOR_ACCURACY, COLOR_MACRO_F1],
            ),
            legend=alt.Legend(title=None, orient="top"),
        ),
    )
    labels = base.mark_text(
        dy=-9, fontSize=12, color="#52514e",
    ).encode(text=alt.Text("Wert:Q", format=".2f"))

    targets = pd.DataFrame([
        {
            "Ziel": TARGET_ACCURACY,
            "Text": f"Ziel Accuracy {TARGET_ACCURACY:.2f}",
            "Farbe": COLOR_ACCURACY,
        },
        {
            "Ziel": TARGET_MACRO_F1,
            "Text": f"Ziel Macro-F1 {TARGET_MACRO_F1:.2f}",
            "Farbe": COLOR_MACRO_F1,
        },
    ])
    rules = alt.Chart(targets).mark_rule(
        strokeDash=[5, 4], strokeWidth=1.5, opacity=0.8,
    ).encode(
        y=alt.Y("Ziel:Q"),
        color=alt.Color("Farbe:N", scale=None, legend=None),
        tooltip=[alt.Tooltip("Text:N", title="Zielwert")],
    )
    rule_labels = alt.Chart(targets).mark_text(
        align="left", dx=6, dy=-6, fontSize=10, opacity=0.9,
    ).encode(
        y=alt.Y("Ziel:Q"),
        text=alt.Text("Text:N"),
        color=alt.Color("Farbe:N", scale=None, legend=None),
    )
    layers = [bars, labels, rules, rule_labels]

    if pending:
        waiting = alt.Chart(pd.DataFrame(pending)).mark_text(
            fontSize=11, opacity=0.5, angle=270,
        ).encode(
            x=alt.X("Version:N", sort=axis_order,
                    scale=alt.Scale(domain=axis_order)),
            y=alt.value(230),
            text=alt.Text("Hinweis:N"),
        )
        layers.append(waiting)

    return alt.layer(*layers).properties(height=320)


PROMPT_BOX = (
    'white-space:pre-wrap;word-break:break-word;background:#ffffff;'
    'color:#111827;border:1px solid #e5e7eb;border-radius:6px;'
    'padding:0.75rem;margin:0;font-size:0.82rem;line-height:1.6;'
    'font-family:ui-monospace,SFMono-Regular,Menlo,monospace'
)
PROMPT_REMOVED = (
    'background:#fdebeb;color:#b22d2d;text-decoration:line-through;'
    'border-radius:3px;padding:0 2px'
)
PROMPT_ADDED = (
    'background:#e8f5ec;color:#22784a;font-weight:600;'
    'border-radius:3px;padding:0 2px'
)
PROMPT_VERSIONS = ("V1", "V2", "V3")


def prompt_texts(version):
    """Die unterschiedlichen Texte einer Version, je Text die Anbieter.

    Die Versionen sind anbieterunabhaengig gedacht. Steht fuer Gemini
    und OpenAI derselbe Text, erscheint er nur einmal. Leere Eintraege
    gelten als noch nicht definiert.
    """
    from backend.keyword_classifier import CATEGORY_GUIDANCE
    from backend.evaluation.evaluate import load_env
    from backend.llms.gemini import configured_categories
    from backend.llms.prompts import PROMPTS, render_prompt

    categories = configured_categories(load_env().get("LLM_CATEGORIES", ""))
    found = {}
    for provider, template in PROMPTS.get(version, {}).items():
        if template.strip():
            text = render_prompt(
                version, provider, categories, category_guidance=CATEGORY_GUIDANCE,
            )
            found.setdefault(text, []).append(provider)
    return found


def prompt_baseline(version):
    """Die zuletzt davor definierte Version als Vergleichsgrundlage.

    V2 wird gegen V1 verglichen, V3 gegen V2. Ist die direkte
    Vorgaengerin noch leer, wird die naechste davor genommen. Gibt es
    keine, entfaellt der Vergleich.
    """
    index = PROMPT_VERSIONS.index(version)
    for earlier in reversed(PROMPT_VERSIONS[:index]):
        texts = list(prompt_texts(earlier))
        if texts:
            return earlier, texts[0]
    return None, ""


def prompt_words(text):
    """Woerter samt folgendem Leerraum, damit der Umbruch erhalten bleibt."""
    return re.findall(r"\S+\s*", text)


def prompt_diff_html(old, new):
    """Wortweiser Vergleich: rot durchgestrichen raus, gruen rein."""
    before, after = prompt_words(old), prompt_words(new)
    matcher = difflib.SequenceMatcher(None, before, after)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(escape("".join(before[i1:i2])))
            continue
        if tag in ("replace", "delete"):
            gone = escape("".join(before[i1:i2]))
            parts.append(f'<span style="{PROMPT_REMOVED}">{gone}</span>')
        if tag in ("replace", "insert"):
            fresh = escape("".join(after[j1:j2]))
            parts.append(f'<span style="{PROMPT_ADDED}">{fresh}</span>')
    return f'<pre style="{PROMPT_BOX}">{"".join(parts)}</pre>'


def render_prompts():
    """Je Prompt-Version eine aufklappbare Karte mit dem echten Text.

    Der Text wird bei jedem Durchlauf frisch aus backend/llms/prompts.py
    gelesen und nicht zwischengespeichert. Nach einem Neuladen des
    Dashboards steht hier also immer der aktuelle Stand. Ab der
    zweiten Version kommt ein Vergleich zur Vorgaengerin dazu.
    """
    st.caption(
        "Verwendete Prompts – ohne diese Angabe ist ein Ergebnis "
        "nicht nachvollziehbar."
    )
    for version in PROMPT_VERSIONS:
        found = prompt_texts(version)
        with st.expander(f"Prompt {version}", expanded=False):
            if not found:
                st.markdown("_Noch nicht definiert_")
                continue
            st.caption("Vollständiger Text")
            for current, providers in found.items():
                if len(found) > 1:
                    st.caption(" / ".join(sorted(providers)))
                st.html(
                    f'<pre style="{PROMPT_BOX}">'
                    f'{escape(current)}</pre>'
                )
            earlier, baseline = prompt_baseline(version)
            if earlier is None:
                st.caption("Ausgangsversion – kein Vergleich möglich.")
                continue
            st.caption(f"Änderungen gegenüber {earlier}")
            st.html(prompt_diff_html(baseline, list(found)[0]))


def available_matrix_versions(mode):
    """Verfahren, zu denen es fuer diesen Modus eine Ergebnisdatei gibt.

    Nur gemessene Laeufe stehen zur Auswahl. Durch den gemeinsamen
    Modus und dieselbe Batch-Einstellung liegt beiden Matrizen
    zwangslaeufig dieselbe Ticket-Stichprobe zugrunde.
    """
    batch = st.session_state.get("batch_evaluation", True)
    return [
        key for key in PROVIDERS
        if key in {v["provider"] for v in VERSIONS} and results_path(key, mode, batch=batch).is_file()
    ]


def default_matrix_pair(options):
    """Zwei aufeinanderfolgende Prompt-Versionen desselben Anbieters.

    Gibt es kein solches Paar, werden die beiden zuletzt gemessenen
    Verfahren genommen.
    """
    for later in reversed(options):
        method = PROVIDERS[later]
        version = method.get("prompt_version")
        name = method.get("provider")
        if not version or version not in PROMPT_VERSIONS:
            continue
        index = PROMPT_VERSIONS.index(version)
        if index == 0:
            continue
        earlier = f"{name}-{PROMPT_VERSIONS[index - 1].lower()}"
        if earlier in options:
            return earlier, later
    if len(options) >= 2:
        return options[-2], options[-1]
    return options[0], options[0]


def align_matrices(first, second):
    """Beide Matrizen auf dieselbe Reihenfolge der Kategorien bringen.

    Zeilen und Spalten sind danach identisch, damit die Zellen
    nebeneinander wirklich dasselbe Feld meinen. Spalten wie [FEHLER]
    stehen hinten.
    """
    names = list(first.columns) + list(second.columns)
    labels = sorted({n for n in names if not n.startswith("[")})
    extra = sorted({n for n in names if n.startswith("[")})
    rows = sorted(set(first.index) | set(second.index))
    order = labels + extra
    return tuple(
        frame.reindex(index=rows, columns=order, fill_value=0)
        .fillna(0).astype(int)
        for frame in (first, second)
    )


def render_matrix_comparison(mode):
    """Zwei Confusion-Matrizen desselben Datensatzes untereinander.

    Zur Auswahl stehen alle Verfahren, auch die noch nicht gemessenen -
    so ist sichtbar, was spaeter dazukommt. Streamlit kann einzelne
    Eintraege nicht sperren, deshalb sind sie beschriftet. Eine noch
    nicht gemessene Version zeigt dieselbe Tabelle mit lauter Nullen,
    damit das Vergleichsbild von Anfang an steht.
    """
    st.subheader("Confusion-Matrix")
    st.caption(
        "Zeilen: richtige Kategorie, Spalten: Antwort des Modells. "
        "Die Diagonale zeigt die richtigen Antworten. "
        "[FEHLER] bedeutet: Die Anfrage an das Modell ist "
        "fehlgeschlagen."
    )
    options = [v["provider"] for v in VERSIONS]
    measured = available_matrix_versions(mode)
    batch = st.session_state.get("batch_evaluation", True)

    def rows_of(key):
        if key not in PROVIDERS or missing_prompt_message(key):
            return []
        path = results_path(key, mode, batch=batch)
        return load_results(path) if path.is_file() else []

    def label_of(key):
        rows = rows_of(key)
        label = model_label(key, rows)
        return label if rows else label + " · noch nicht gemessen"

    defaults = default_matrix_pair(measured) if measured else (options[0], options[-1])
    for title, default, side in (("Vorherige Version", defaults[0], "left"),
                                 ("Neue Version", defaults[1], "right")):
        key = st.selectbox(title, options=options, index=options.index(default),
                           format_func=label_of, key=f"matrix_{side}_{mode}")
        rows = rows_of(key)
        if not rows:
            st.info("Nicht unterstützt – kein Evaluation-Adapter." if key not in PROVIDERS
                    else "Noch nicht gemessen – keine Confusion-Matrix verfügbar.")
            continue
        st.dataframe(confusion_matrix(rows).style.apply(matrix_styles, axis=None), width="stretch")


def render_version_comparison(mode=None):
    """Vergleichstabelle und Entwicklungsdiagramm der Versionen."""
    measured = {}
    for version in VERSIONS:
        data = version_metrics(version, mode)
        if data is not None:
            measured[version["key"]] = data

    missing = [comparison_label(v, measured) for v in VERSIONS if v["key"] not in measured]

    st.subheader("Ergebnisse pro Kategorie und Version")
    st.caption(
        "P = Precision, R = Recall. Werte zwischen 0 und 1, "
        "Bestwert 1.00."
    )
    for prompt in ("V1", "V2", "V3"):
        group = [VERSIONS[0]] + [v for v in VERSIONS[1:]
                                 if v["key"].endswith("-" + prompt.lower())]
        st.markdown(f"### {prompt}")
        st.html(version_table_html(measured, group))
    if missing:
        st.caption(
            "Ohne Messung (angezeigtes Modell ist konfiguriert): " + ", ".join(missing)
            + ". Sobald eine Version eine Ergebnisdatei hat, füllen "
            "sich Tabelle und Diagramm von selbst."
        )

    st.divider()

    render_prompts()

    st.divider()

    render_matrix_comparison(mode)

    st.divider()

    st.subheader("Entwicklung im Vergleich")
    st.caption(
        "Accuracy = Trefferquote. "
        "Macro-F1 = durchschnittliches F1 über alle Kategorien."
    )
    st.altair_chart(version_chart(measured), width="stretch")


def main():
    global VERSIONS
    VERSIONS = configured_versions()
    st.set_page_config(
        page_title="Evaluation – Ticket-Klassifikator",
        page_icon="📊",
        layout="wide",
    )

    provider, mode, prompt_missing = render_sidebar()
    if prompt_missing:
        st.title("Ticket-Klassifikator – Evaluation")
        st.info(prompt_missing)
        render_version_comparison(mode)
        return

    path = results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True) and provider.split("-")[0] != "local")
    if not path.is_file():
        st.title("Ticket-Klassifikator – Evaluation")
        st.warning(
            f"Für \"{model_label(provider)}\" mit der Quelle "
            f"\"{MODES[mode]['label']}\" gibt es noch keine Ergebnisse. "
            "Bitte links auf \"Evaluation neu ausführen\" klicken."
        )
        render_version_comparison(mode)
        return

    results = load_results(path)
    if not results:
        st.warning("Die Ergebnisdatei ist leer.")
        return

    render_header(results, provider, path, mode)
    if all(result.get("error") for result in results):
        st.error("Keine gültigen Vorhersagen: Alle Anfragen sind fehlgeschlagen. Accuracy und F1 sind nicht auswertbar.")
        st.subheader("Anfragefehler")
        from collections import Counter
        st.dataframe([{"Fehler": error, "Tickets": count}
                      for error, count in Counter(r.get("error") for r in results).items()],
                     width="stretch")
        render_version_comparison(mode)
        st.subheader("Alle Tickets")
        st.dataframe(for_display(results), width="stretch")
        return
    render_kpis(results)
    st.divider()

    render_version_comparison(mode)
    st.divider()

    st.subheader("Alle Tickets")
    st.dataframe(for_display(results), width="stretch")

    st.subheader("Fehlklassifikationen")
    errors = misclassifications(results)
    if errors:
        st.dataframe(for_display(errors), width="stretch")
    else:
        st.info("Keine Fehlklassifikationen.")

    render_backlog()


def render_backlog():
    """Offene Ideen, die bewusst noch nicht umgesetzt sind."""
    st.divider()
    with st.expander("Mögliche Erweiterungen (noch nicht umgesetzt)"):
        st.markdown(BACKLOG)


if __name__ == "__main__":
    main()
