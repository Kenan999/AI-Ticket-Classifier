"""Streamlit-Dashboard fuer die Evaluation V0.

Liest results/evaluation/evaluation_v0.csv und zeigt Accuracy, Macro-F1
und die Fehlklassifikationen. Die Kennzahlen werden mit den Funktionen
aus evaluation/evaluate.py berechnet, damit Dashboard und Konsole immer
dieselben Werte zeigen.

Starten aus dem Projekt-Root:
    streamlit run evaluation/dashboard.py
"""

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
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.evaluate import (  # noqa: E402
    RESULTS_PATH,
    accuracy,
    macro_f1,
    misclassifications,
    per_category_scores,
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

# Prompt-Versionen. V0 ist die Keyword-Baseline, V1-V3 sind spaetere
# Prompt-Varianten. "path" bleibt None, solange nichts gemessen wurde -
# dann steht in Tabelle und Diagramm nichts, niemals erfundene Zahlen.
CURRENT_VERSION = "V0"
VERSIONS = [
    {
        "key": "V0",
        "short": "V0 · Baseline",
        "path": RESULTS_PATH,
        "tint": "#eaf2fc",
        "ink": "#1b5fae",
        "approach": "Regeln, kein LLM",
        "prompt": (
            "Kein Prompt. Gezählte Stichwörter mit festen Punktwerten "
            "in backend/classifier.py."
        ),
    },
    {
        "key": "V1",
        "short": "Prompt V1",
        "path": None,
        "tint": "#fdf0ea",
        "ink": "#a8451c",
        "approach": "Gemini",
        "prompt": None,
    },
    {
        "key": "V2",
        "short": "Prompt V2",
        "path": None,
        "tint": "#e9f7f1",
        "ink": "#107954",
        "approach": "Gemini",
        "prompt": None,
    },
    {
        "key": "V3",
        "short": "Prompt V3",
        "path": None,
        "tint": "#efedfb",
        "ink": "#4a3bb0",
        "approach": "Gemini",
        "prompt": None,
    },
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
  "V3 ist besser als V2, Hauptschwäche bleibt Returns".
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


def last_run(path=RESULTS_PATH):
    """Zeitpunkt des letzten Laufs, aus dem Dateidatum der CSV."""
    if not path.is_file():
        return None
    stamp = datetime.fromtimestamp(path.stat().st_mtime)
    return stamp.strftime("%d.%m.%Y um %H:%M Uhr")


def load_results(path=RESULTS_PATH):
    """Liest die CSV und baut die Ergebnisliste wieder auf.

    "correct" wird neu aus expected und predicted bestimmt, damit das
    Dashboard nicht davon abhaengt, wie die CSV True/False einliest.
    """
    frame = pd.read_csv(path)
    results = []
    for row in frame.to_dict(orient="records"):
        results.append({
            "text": row["text"],
            "expected": row["expected"],
            "predicted": row["predicted"],
            "confidence": row["confidence"],
            "model_version": row["model_version"],
            "correct": row["expected"] == row["predicted"],
        })
    return results


def render_sidebar(results):
    """Steuerung und Angaben zur Datenquelle in der Seitenleiste."""
    with st.sidebar:
        st.header("Steuerung")
        if st.button("Evaluation neu ausführen", width="stretch"):
            save_results(run_evaluation())
            st.success("Neu berechnet und gespeichert.")
            st.rerun()

        if results:
            st.divider()
            st.caption("Ergebnisdatei")
            st.code(RESULTS_PATH.name, language=None)
            versions = sorted({row["model_version"] for row in results})
            st.caption("Gemessenes Modell")
            for version in versions:
                st.code(version, language=None)


def render_header(results):
    """Titel, Versionskennzeichen und Hinweis auf die Testdaten."""
    title, badge = st.columns([5, 1], vertical_alignment="center")
    title.title("Ticket-Klassifikator – Evaluation")
    badge.success("Version V0")
    stamp = last_run()
    if stamp:
        st.caption(f"Letzte Messung: {stamp}")
    st.warning(
        f"**V0 nutzt {len(results)} synthetische Test-Tickets** – "
        "selbst geschriebene, eindeutige Beispiele. Die Werte zeigen, "
        "dass die Messung funktioniert, nicht wie gut der Klassifikator "
        "bei echten Kundentickets ist.",
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

    with st.expander("Was bedeuten diese Kennzahlen?"):
        st.markdown(METRIC_EXPLANATIONS)


def version_metrics(version):
    """Kennzahlen einer Version, oder None wenn sie fehlt.

    Eine Version ohne Ergebnisdatei liefert bewusst None. Es werden
    niemals Platzhalterzahlen erfunden.
    """
    path = version["path"]
    if path is None or not path.is_file():
        return None
    results = load_results(path)
    if not results:
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


def render_prompts(measured):
    """Je Version eine Karte mit dem verwendeten Prompt.

    Bewusst ohne Aufklappen: beim Vergleich von Prompt-Varianten will
    man die Unterschiede direkt nebeneinander sehen.
    """
    st.caption(
        "Verwendete Prompts – ohne diese Angabe ist ein Ergebnis "
        "nicht nachvollziehbar."
    )

    columns = st.columns(len(VERSIONS), gap="small")
    for column, version in zip(columns, VERSIONS):
        done = version["key"] in measured
        with column, st.container(border=True, height=170):
            st.html(
                f'<div style="background:{version["tint"]};'
                f'color:{version["ink"]};padding:0.35rem 0.6rem;'
                f'border-radius:6px;font-weight:600;font-size:0.9rem">'
                f'{escape(version["short"])}</div>'
            )
            st.caption(
                f"{version['approach']} · "
                + ("gemessen" if done else "noch offen")
            )
            if version["prompt"]:
                st.markdown(version["prompt"])
            else:
                st.markdown("_Prompt noch nicht festgelegt._")


def render_version_comparison(results):
    """Vergleichstabelle und Entwicklungsdiagramm der Versionen."""
    measured = {}
    for version in VERSIONS:
        data = (
            {
                "results": results,
                "scores": per_category_scores(results),
                "accuracy": accuracy(results),
                "macro_f1": macro_f1(results),
            }
            if version["key"] == CURRENT_VERSION
            else version_metrics(version)
        )
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
            "Noch nicht gemessen: " + ", ".join(missing)
            + ". Sobald eine Version eine Ergebnisdatei hat, füllen "
            "sich Tabelle und Diagramm von selbst."
        )

    st.divider()

    st.subheader("Entwicklung im Vergleich")
    st.caption(
        "Accuracy = Trefferquote. "
        "Macro-F1 = durchschnittliches F1 über alle Kategorien."
    )
    st.altair_chart(version_chart(measured), width="stretch")

    render_prompts(measured)


def main():
    st.set_page_config(
        page_title="Evaluation – Ticket-Klassifikator",
        page_icon="📊",
        layout="wide",
    )

    if not RESULTS_PATH.is_file():
        st.title("Ticket-Klassifikator – Evaluation")
        st.warning(
            "Noch keine Ergebnisse vorhanden. Bitte links auf "
            "\"Evaluation neu ausführen\" klicken."
        )
        render_sidebar([])
        return

    results = load_results()
    if not results:
        st.warning("Die Ergebnisdatei ist leer.")
        render_sidebar([])
        return

    render_sidebar(results)
    render_header(results)
    render_kpis(results)
    st.divider()

    render_version_comparison(results)
    st.divider()

    st.subheader("Alle Tickets")
    st.dataframe(pd.DataFrame(results), width="stretch")

    st.subheader("Fehlklassifikationen")
    errors = misclassifications(results)
    if errors:
        st.dataframe(pd.DataFrame(errors), width="stretch")
    else:
        st.info("Keine Fehlklassifikationen.")

    render_backlog()


def render_backlog():
    """Offene Ideen, die bewusst noch nicht umgesetzt sind."""
    st.divider()
    with st.expander("Mögliche Erweiterungen (noch nicht umgesetzt)"):
        st.markdown(BACKLOG)


main()
