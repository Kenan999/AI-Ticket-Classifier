"""Standalone, read-only Streamlit observation dashboard."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]


def database_path():
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    path = Path(config["database"]["path"]).expanduser()
    return path if path.is_absolute() else ROOT / path


def load_rows(path, source):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        query = "SELECT * FROM observations"
        params = []
        if source != "Alle":
            query += " WHERE source=?"
            params.append(source)
        query += " ORDER BY created_at DESC, id DESC"
        return [dict(row) for row in db.execute(query, params)]


def status(row):
    return "Fehler" if row["error_json"] is not None else (
        "Abgeschlossen" if row["completed_at"] else "Antwort ausstehend")


def render():
    st.set_page_config(page_title="Observation", page_icon="🔎", layout="wide")
    st.html("<style>.stMainBlockContainer {padding-top: 3rem; padding-bottom: 1rem;} </style>")
    st.subheader("Observation")
    source_column, provider_column, refresh_column = st.columns([2, 2, 1], vertical_alignment="bottom")
    source = source_column.selectbox("Quelle", ["Alle", "application", "evaluation"],
                          format_func=lambda value: {"Alle": "Alle", "application": "Ticketanfragen",
                                                      "evaluation": "Evaluationen"}[value])
    refresh_column.button("Aktualisieren", width="stretch")
    path = database_path()
    if not path.is_file():
        st.info("Noch keine Datenbank vorhanden. Starte zuerst den Observation-Dienst.")
        return
    try:
        rows = load_rows(path, source)
    except sqlite3.Error:
        st.error("Observation-Datenbank nicht lesbar oder noch nicht initialisiert.")
        return
    if not rows:
        st.info("Noch keine Anfragen gespeichert. Backend und Evaluation sind noch nicht an Observation angebunden.")
        return
    provider = provider_column.selectbox("Anbieter", ["Alle"] + sorted({r["provider"] for r in rows}))
    if provider != "Alle":
        rows = [r for r in rows if r["provider"] == provider]
    groups = {}
    for row in rows:
        key = row.get("run_id") or row["id"]
        groups.setdefault(key, []).append(row)
    groups = dict(list(groups.items())[:200])
    rows = [row for group in groups.values() for row in group]
    pending = sum(not r["completed_at"] for r in rows)
    failed = sum(r["error_json"] is not None for r in rows)
    st.caption(f"{len(groups)} Läufe · {len(rows)} Anfragen · {pending} ausstehend · {failed} Fehler · Neueste 200 Läufe")
    for run_id, requests in groups.items():
        label = f"{requests[0]['created_at']} · Lauf · {len(requests)} Anfragen"
        with st.expander(label):
            st.caption(f"Lauf-Kennung: {run_id}")
            _, content = st.columns([1, 30])
            with content:
                for number, row in enumerate(reversed(requests), 1):
                    with st.expander(f"{number}. {row['provider']} · {row['model']} · {status(row)}"):
                        st.caption(f"Quelle: {row['source']} · Kennung: {row['id']} · Start: {row['created_at']}")
                        if row["completed_at"]:
                            try:
                                seconds = (datetime.fromisoformat(row["completed_at"]) -
                                           datetime.fromisoformat(row["created_at"])).total_seconds()
                                st.caption(f"Dauer: {seconds:.2f} Sekunden")
                            except (TypeError, ValueError):
                                st.caption("Dauer nicht verfügbar.")
                        for title, field in (("Anfrage", "request_json"), ("Antwort", "response_json"), ("Fehler", "error_json")):
                            if row[field] is not None:
                                st.markdown(f"**{title}**")
                                try:
                                    st.json(json.loads(row[field]))
                                except (TypeError, ValueError):
                                    st.text(row[field])


if __name__ == "__main__":
    render()
