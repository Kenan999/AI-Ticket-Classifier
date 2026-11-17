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
            "in backend/classifier.py."
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

TABLE_STYLE = """
<style>
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
.ev-sub { font-weight: 500; opacity: 0.75; font-size: 0.78rem; }
.ev-corner { background: transparent; }
.ev-name { text-align: left; font-weight: 500; white-space: nowrap; }
.ev-value { opacity: 0.85; }
.ev-strong { font-weight: 700; opacity: 1; }
.ev-empty { opacity: 0.35; }
.ev-total { font-weight: 700; }
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
        engine = st.selectbox(
            "3. Verfahren", options=[BASELINE, "gemini", "openai"],
            format_func=lambda key: {BASELINE: "Lokale Regeln", "gemini": "Gemini", "openai": "OpenAI"}[key],
            help="Lokale Regeln brauchen keinen Prompt. Gemini und OpenAI benötigen einen API-Key.",
        )
        with prompt_controls:
            version = st.selectbox(
                "2. Prompt-Version", options=["V1", "V2", "V3"],
                disabled=engine == BASELINE,
                help="V2 und V3 bleiben gesperrt, bis ihre Prompts eingetragen sind.",
            )
            if engine == BASELINE:
                st.caption("Nicht erforderlich: Lokale Regeln verwenden keinen Prompt.")
        provider = BASELINE if engine == BASELINE else f"{engine}-{version.lower()}"
        if engine != BASELINE:
            from backend.evaluation.evaluate import load_env
            from backend.llms.gemini import DEFAULT_MODEL
            active_model = load_env().get(engine.upper() + "_MODEL", DEFAULT_MODEL if engine == "gemini" else "gpt-4.1-mini")
            st.caption(f"Modell für neue Tests: {active_model}")
        st.checkbox("Tickets gemeinsam senden (Batch)", value=True,
                    key="batch_evaluation", disabled=engine == BASELINE)
        if engine != BASELINE and st.session_state.get("batch_evaluation", True):
            st.caption("Batch-Limits: evaluation/config.py. Automatische Gruppengröße nach Textlänge und Token-Budget; kein festes 20-Ticket-Limit. Alte Einzel-Ergebnisse: Batch ausschalten.")
        prompt_missing = missing_prompt_message(provider)
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
                    measured = run_evaluation(progress=show_progress,batch=st.session_state.get("batch_evaluation", True),
                        tickets=tickets, provider=provider,
                    )
                    save_results(
                        measured, results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True)),
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
        st.code(results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True)).name, language=None)
        return provider, mode, prompt_missing


def render_header(results, provider, path, mode=None):
    """Titel, gewaehltes Verfahren und Hinweis zur Datenquelle."""
    title, badge = st.columns([4, 2], vertical_alignment="center")
    title.title("Ticket-Klassifikator – Evaluation")
    badge.success(PROVIDERS[provider]["label"])
    stamp = last_run(path)
    models = sorted({row["model_version"] for row in results})
    if stamp:
        st.caption(
            f"Letzte Messung: {stamp} · Modell: {', '.join(models)}"
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
    if provider is None or missing_prompt_message(provider):
        return None
    path = results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True))
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


def version_table_html(measured):
    """Baut die Vergleichstabelle als HTML.

    Zeilen sind Kategorien, je Version eine Spaltengruppe mit
    Precision, Recall und F1. Unten Macro-F1 und Accuracy.
    """
    categories = []
    for data in measured.values():
        for category in data["scores"]:
            if category not in categories:
                categories.append(category)
    categories.sort()

    head_top = ['<th class="ev-corner">Kategorie</th>']
    head_sub = []
    for version in VERSIONS:
        key = version["key"]
        head_top.append(
            f'<th colspan="3" class="ev-group" '
            f'style="background:{version["tint"]};'
            f'color:{version["ink"]}">{escape(version["short"])}</th>'
        )
        for metric in ("P", "R", "F1"):
            head_sub.append(
                f'<th class="ev-sub" '
                f'style="background:{version["tint"]}">{metric}</th>'
            )

    body = []
    for category in categories:
        cells = [f'<td class="ev-name">{escape(category)}</td>']
        for version in VERSIONS:
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
        for version in VERSIONS:
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
    value_columns = len(VERSIONS) * 3
    colgroup = (
        '<colgroup><col style="width:16%">'
        + f'<col style="width:{84 / value_columns:.3f}%">' * value_columns
        + "</colgroup>"
    )

    return (
        TABLE_STYLE
        + '<table class="ev-table">'
        + colgroup
        + "<thead><tr>"
        + "".join(head_top)
        + '</tr><tr><th class="ev-corner"></th>'
        + "".join(head_sub)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
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
            pending.append({"Version": version["short"], "Hinweis": "offen"})
            rows.append({
                "Version": version["short"],
                "Kennzahl": "Accuracy",
                "Wert": None,
            })
            rows.append({
                "Version": version["short"],
                "Kennzahl": "Macro-F1",
                "Wert": None,
            })
            continue
        rows.append({
            "Version": version["short"],
            "Kennzahl": "Accuracy",
            "Wert": round(data["accuracy"], 2),
        })
        rows.append({
            "Version": version["short"],
            "Kennzahl": "Macro-F1",
            "Wert": round(data["macro_f1"], 2),
        })
    frame = pd.DataFrame(rows)
    axis_order = [version["short"] for version in VERSIONS]
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
    from backend.llms.prompts import PROMPTS

    found = {}
    for provider, text in PROMPTS.get(version, {}).items():
        if text.strip():
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
        if results_path(key, mode, batch=batch).is_file()
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
    measured = available_matrix_versions(mode)
    if not measured:
        st.info("Für diesen Datensatz liegt noch kein Ergebnis vor.")
        return

    options = list(PROVIDERS)
    done = set(measured)

    def label_of(key):
        label = PROVIDERS[key]["label"]
        return label if key in done else f"{label} · noch nicht gemessen"

    def matrix_of(key):
        rows = load_results(results_path(key, mode, batch=batch))
        return confusion_matrix(rows) if rows else None

    batch = st.session_state.get("batch_evaluation", True)
    left_default, right_default = default_matrix_pair(measured)

    # Auswahl und zugehoerige Tabelle stehen direkt untereinander.
    # Die Behaelter werden hier belegt, gefuellt wird nach dem Laden.
    left = st.selectbox(
        "Vorherige Version", options=options,
        index=options.index(left_default),
        format_func=label_of, key=f"matrix_left_{mode}",
    )
    left_slot = st.container()
    right = st.selectbox(
        "Neue Version", options=options,
        index=options.index(right_default),
        format_func=label_of, key=f"matrix_right_{mode}",
    )
    right_slot = st.container()

    frames = {}
    for key in dict.fromkeys((left, right)):
        if key in done:
            frame = matrix_of(key)
            if frame is not None:
                frames[key] = frame

    # Vorlage fuer die Nullen-Tabelle: irgendeine gemessene Matrix
    # liefert die Kategorien, damit beide Tabellen gleich aussehen.
    template = next(iter(frames.values()), None)
    if template is None:
        template = matrix_of(measured[0])
    if template is None:
        st.info("Für diesen Datensatz liegt noch kein Ergebnis vor.")
        return

    shown = {
        key: frames.get(key, template * 0)
        for key in dict.fromkeys((left, right))
    }
    if left != right:
        first, second = align_matrices(shown[left], shown[right])
        shown[left], shown[right] = first, second

    for slot, key in ((left_slot, left), (right_slot, right)):
        with slot:
            if key not in frames:
                st.caption(
                    "Noch nicht gemessen – alle Werte 0. Sobald ein "
                    "Lauf vorliegt, stehen hier die echten Zahlen."
                )
            st.dataframe(
                shown[key].style.apply(matrix_styles, axis=None),
                width="stretch",
            )


def render_version_comparison(mode=None):
    """Vergleichstabelle und Entwicklungsdiagramm der Versionen."""
    measured = {}
    for version in VERSIONS:
        data = version_metrics(version, mode)
        if data is not None:
            measured[version["key"]] = data

    missing = [v["short"] for v in VERSIONS if v["key"] not in measured]

    st.subheader("Ergebnisse pro Kategorie und Version")
    st.caption(
        "P = Precision, R = Recall. Werte zwischen 0 und 1, "
        "Bestwert 1.00."
    )
    st.html(version_table_html(measured))
    if missing:
        st.caption(
            "Keine auswertbaren Ergebnisse: " + ", ".join(missing)
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
    st.set_page_config(
        page_title="Evaluation – Ticket-Klassifikator",
        page_icon="📊",
        layout="wide",
    )

    provider, mode, prompt_missing = render_sidebar()
    path = results_path(provider, mode, batch=st.session_state.get("batch_evaluation", True))

    if prompt_missing:
        st.title("Ticket-Klassifikator – Evaluation")
        st.info(prompt_missing)
        return

    if not path.is_file():
        st.title("Ticket-Klassifikator – Evaluation")
        st.warning(
            f"Für \"{PROVIDERS[provider]['label']}\" mit der Quelle "
            f"\"{MODES[mode]['label']}\" gibt es noch keine Ergebnisse. "
            "Bitte links auf \"Evaluation neu ausführen\" klicken."
        )
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


main()
