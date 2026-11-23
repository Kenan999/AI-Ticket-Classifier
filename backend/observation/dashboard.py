"""Standalone, read-only Streamlit observation dashboard."""
import json
import base64
import html
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.observation.metrics import request_metrics, safe_response_headers


def observation_config(models=None):
    """Receive model metadata as an object; keep local observation settings separate."""
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    if models is None:
        # Composition boundary: the backend supplies the project's registry.
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from backend.llms.registry import model_configuration
        models = model_configuration(test_environment())
    config["llms"] = [dict(item) for item in models["llms"]]
    return config


def database_path():
    config = observation_config()
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


def group_kind(rows):
    """Chat session requests are conversations, not processing loops."""
    if rows and all(row.get("source") == "chat" for row in rows):
        return "conversation" if len(rows) > 1 else "single"
    return "loop" if len(rows) > 1 else "single"


def loop_marker(rows):
    """Static speech-bubble icon for multi-turn chat; original glyph for loops."""
    kind = group_kind(rows)
    if kind == "conversation":
        path = ('<path d="M5 4h14a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H9l-6 3V7a3 3 0 0 1 3-3z" '
                'fill="none" stroke="#9aa9e8" stroke-width="1.7" stroke-linejoin="round"/>'
                '<circle cx="9" cy="12" r="1.15" fill="#9aa9e8"/>'
                '<circle cx="13" cy="12" r="1.15" fill="#9aa9e8"/>'
                '<circle cx="17" cy="12" r="1.15" fill="#9aa9e8"/>')
        alt = "conversation-static"
    elif kind == "loop":
        path = '<path d="M7 7h10v3l4-4-4-4v3H5v6h2zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2z" fill="#8b95a5"/>'
        alt = "loop-animated"
    else:
        path = ""
        alt = "loop-slot"
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">{path}</svg>'
    return f"![{alt}](data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()})"


def display_model(provider, model):
    if provider == "local" and "Qwen3-4B" in str(model):
        return "Qwen3-4B (4-bit)"
    return str(model)


def provider_logos(rows):
    """Model labels with the existing provider logos and a local Qwen icon."""
    parts = []
    for provider, model in sorted({(row["provider"], row["model"]) for row in rows}):
        if provider not in {"openai", "gemini", "local"}:
            continue
        logo = "qwen" if provider == "local" else provider
        path = Path(__file__).with_name("assets") / (logo + ".svg")
        if path.is_file():
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            image = f'<img src="data:image/svg+xml;base64,{data}" alt="{html.escape(logo)}" style="width:22px;height:22px;object-fit:contain;flex:none">'
        else:
            image = ""
        parts.append(f'<span style="display:inline-flex;align-items:center;gap:9px;min-width:0">{image}<span style="overflow-wrap:anywhere">{html.escape(display_model(provider, model))}</span></span>')
    return "<span style='display:flex;flex-wrap:wrap;gap:12px'>" + "".join(parts) + "</span>"


def provider_logos_markdown(rows):
    """Streamlit expander labels require Markdown images, not raw HTML."""
    parts = []
    for provider, model in sorted({(row["provider"], row["model"]) for row in rows}):
        logo = "qwen" if provider == "local" and "Qwen" in model else provider
        path = Path(__file__).with_name("assets") / (logo + ".svg")
        icon = ""
        if path.is_file():
            icon = f"![{logo}](data:image/svg+xml;base64,{base64.b64encode(path.read_bytes()).decode()}) "
        parts.append(icon + f"`{display_model(provider, model).replace(chr(96), '')}`")
    return " ".join(parts)


def effective_cost(row):
    if row["provider"] == "local" and "Qwen3-4B" in str(row["model"]):
        return 0.0
    return stored_metrics(row).get("estimated_standard_cost_usd")


def run_cost(rows):
    costs = [effective_cost(row) for row in rows]
    known = [cost for cost in costs if isinstance(cost, (int, float)) and not isinstance(cost, bool)]
    if not known:
        return "Kosten: unbekannt"
    suffix = " (unvollständig)" if len(known) != len(costs) else ""
    if all(row["provider"] == "local" and "Qwen3-4B" in str(row["model"]) for row in rows):
        return "$0.00 API-Kosten"
    return f"≈ ${sum(known):.6f}{suffix}"


def run_duration(rows):
    try:
        start = min(datetime.fromisoformat(r["created_at"]) for r in rows)
        pending = any(not r["completed_at"] for r in rows)
        end = datetime.now(timezone.utc) if pending else max(
            datetime.fromisoformat(r["completed_at"]) for r in rows)
        seconds = max(0, (end - start).total_seconds())
        return f"{seconds:.2f} s" + (" · läuft" if pending else "")
    except (ValueError, TypeError, KeyError):
        return "unbekannt"


def is_loop(rows):
    """Identify actual request loops, not tickets inside one batch."""
    return group_kind(rows) == "loop"


@contextmanager
def status_expander(label, rows, key):
    state = "error" if any(r["error_json"] is not None for r in rows) else "success"
    kind = group_kind(rows)
    with st.container(key=f"obs-{state}-{kind}-{key}"):
        with st.expander(label):
            yield


def status_icon(rows):
    if any(row["error_json"] is not None for row in rows):
        return ":red[:material/cancel:]"
    if any(not row["completed_at"] for row in rows):
        return ":material/hourglass_top:"
    return ":green[:material/check_circle:]"


def status(row):
    return "Fehler" if row["error_json"] is not None else (
        "Abgeschlossen" if row["completed_at"] else "Antwort ausstehend")




class ProviderTestError(ValueError):
    def __init__(self, details):
        self.details = details
        super().__init__(details["summary"])


def provider_error_details(exc, secrets=()):
    from urllib.error import HTTPError
    details = {"summary": "Anfrage fehlgeschlagen oder Zeitlimit erreicht."}
    if not isinstance(exc, HTTPError):
        return details
    details = {"summary": f"Provider meldet HTTP {exc.code}", "http_status": exc.code}
    if exc.headers:
        retry = exc.headers.get("Retry-After")
        if retry:
            details["retry_after"] = str(retry)[:200]
    try:
        raw = exc.read(65537)
        payload = json.loads(raw) if len(raw) <= 65536 else {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if isinstance(error, dict):
            for field in ("message", "code", "type", "status"):
                if isinstance(error.get(field), (str, int)):
                    details[field] = str(error[field])[:4000]
            selected = []
            for item in error.get("details", []) if isinstance(error.get("details"), list) else []:
                if not isinstance(item, dict):
                    continue
                if item.get("@type", "").endswith("google.rpc.RetryInfo"):
                    selected.append({"retry_delay": str(item.get("retryDelay", ""))[:200]})
                elif item.get("@type", "").endswith("google.rpc.QuotaFailure"):
                    for violation in item.get("violations", [])[:20]:
                        if isinstance(violation, dict):
                            selected.append({k: str(violation[k])[:1000] for k in
                                ("quotaMetric", "quotaId", "quotaValue", "description")
                                if k in violation})
            if selected:
                details["quota_details"] = selected
    except (ValueError, OSError, TypeError, AttributeError):
        details["detail_note"] = "Keine lesbaren strukturierten Fehlerdetails erhalten."
    finally:
        exc.close()
    def redact(value):
        if isinstance(value, str):
            for secret in secrets:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value
    return redact(details)



def stored_metrics(row):
    try:
        value = json.loads(row["response_json"] or row["error_json"] or "{}")
        return value.get("_observation", {}) if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def show_metrics(value):
    metadata = value.get("_observation", {}) if isinstance(value, dict) else {}
    if not metadata:
        st.caption("Für diesen älteren Eintrag wurden keine Transport-Metadaten erfasst.")
        return
    cost = metadata.get("estimated_standard_cost_usd")
    st.caption("Geschätzte Standardkosten: " + (f"${cost:.8f}" if cost is not None else "unbekannt"))
    st.caption(metadata.get("cost_note", ""))
    with st.expander("Anfrageinformationen · Tokens, Kosten, Laufzeit und Limits"):
        st.json(metadata)


ANSWER_TOKENS = 1024


def test_environment():
    import os
    env = dict(os.environ)
    env_path = ROOT / "backend" / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key.strip() in {"OPENAI_API_KEY", "GEMINI_API_KEY", "OPENAI_MODEL", "GEMINI_MODEL"}:
                    env.setdefault(key.strip(), value.strip().strip("\"'"))
    return env


def selected_model(provider, model):
    return next((item["model"] for item in observation_config()["llms"]
                 if item["id"] == provider), model)


def request_budget(config, model, text):
    limits = config.get("request_limits", {}).get(model, {})
    # Deliberately conservative local estimate, not provider tokenization.
    estimate = len(text.encode("utf-8")) + 32
    ceiling = limits.get("input_tokens") or limits.get("context_tokens")
    used = estimate + (ANSWER_TOKENS if limits.get("context_tokens") else 0)
    return {"model": model, "estimated_input_tokens": estimate,
            "estimate_method": "UTF-8 bytes + 32; conservative estimate, not exact",
            "answer_tokens": ANSWER_TOKENS, "limits": limits,
            "used": used, "ceiling": ceiling,
            "blocked": bool(ceiling and used > ceiling) or bool(limits.get("output_tokens", ANSWER_TOKENS) < ANSWER_TOKENS)}


def send_test(provider, model, text, run_id=None, run_kind="single"):
    """Send one explicit user-triggered request and record it via the local service."""
    import os
    from urllib.request import Request, urlopen
    config = observation_config()
    env = test_environment()
    key = env.get(provider.upper() + "_API_KEY", "").strip()
    if not key:
        raise ValueError("Für diesen Anbieter ist kein API-Schlüssel konfiguriert.")
    model = selected_model(provider, model)
    budget = request_budget(config, model, text)
    if budget["blocked"]:
        raise ValueError("Lokale Größenprüfung überschritten; Anfrage nicht gesendet.")
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model):
        raise ValueError("Ungültiger Modellname.")
    if provider == "openai":
        url = "https://api.openai.com/v1/chat/completions"
        payload = {"model": model, "messages": [{"role": "user", "content": text}], "max_completion_tokens": ANSWER_TOKENS}
        headers = {"Authorization": "Bearer " + key}
    elif provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
        payload = {"contents": [{"role": "user", "parts": [{"text": text}]}],
                   "generationConfig": {"maxOutputTokens": ANSWER_TOKENS}}
        headers = {"x-goog-api-key": key}
    else:
        raise ValueError("Anbieter wird noch nicht unterstützt.")
    settings = config["service"]
    if settings["host"] != "127.0.0.1":
        raise ValueError("Test-Monitoring ist nur lokal verfügbar.")
    base = "http://127.0.0.1:" + str(int(settings["port"]))
    def post(url, body, method="POST", headers=None, timeout=5, transport=None):
        req = Request(url, data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json", **(headers or {})}, method=method)
        with urlopen(req, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if transport is not None:
                transport.update(http_status=response.status, response_headers=safe_response_headers(response.headers), response_bytes=len(raw))
        if len(raw) > 1024 * 1024:
            raise ValueError("Antwort zu groß.")
        return json.loads(raw)
    import uuid
    ident = post(base + "/observations", {"source": "application", "provider": provider,
                 "model": model, "request": {**payload, "_observation": {"run_kind": run_kind, "request_budget": budget}}, "run_id": run_id or str(uuid.uuid4())})["id"]
    import time
    started = time.perf_counter()
    transport = {"endpoint": url, "method": "POST", "timeout_seconds": 30,
                 "streaming": False, "request_bytes": len(json.dumps(payload).encode()),
                 "run_id": run_id, "observation_id": ident}
    try:
        response = post(url, payload, headers=headers, timeout=30, transport=transport)
    except Exception as exc:
        transport["response_headers"] = safe_response_headers(getattr(exc, "headers", None))
        transport["http_status"] = getattr(exc, "code", None)
        error = provider_error_details(exc, (env.get("OPENAI_API_KEY"), env.get("GEMINI_API_KEY")))
        error["_observation"] = request_metrics(provider, model, {}, time.perf_counter()-started, transport, config)
        try:
            post(base + "/observations/" + ident, {"error": error}, method="PATCH")
        except Exception:
            error["monitoring_warning"] = "Monitoring-Abschluss konnte nicht gespeichert werden."
        raise ProviderTestError(error) from None
    response["_observation"] = request_metrics(provider, model, response, time.perf_counter()-started, transport, config)
    warning = None
    try:
        post(base + "/observations/" + ident, {"response": response}, method="PATCH")
    except Exception:
        warning = "Antwort empfangen, aber Monitoring-Abschluss konnte nicht gespeichert werden."
    return response, warning


@st.dialog("LLM testen", width="small", dismissible=False)
def test_dialog():
    config = observation_config()
    models = config.get("llms", [])
    if not models:
        st.info("Keine LLMs konfiguriert.")
        return
    st.caption("Ein direkter Modelltest, ohne Klassifizierungs-Prompt. Senden nutzt die API und speichert Anfrage und Antwort lokal.")
    mode = st.radio("Testart", ["Einzel", "Loop"], horizontal=True)
    selected = st.selectbox("LLM", range(len(models)),
        format_func=lambda i: models[i]["provider"] + " · " + selected_model(models[i]["id"], models[i]["default_model"]))
    first = st.text_area("Abfrage 1", max_chars=12000)
    second = st.text_area("Abfrage 2", max_chars=12000) if mode == "Loop" else None
    blocked = any(request_budget(config, selected_model(models[selected]["id"], models[selected]["default_model"]), text)["blocked"] for text in ([first, second] if mode == "Loop" else [first]))
    if blocked:
        st.error("Lokale Größenprüfung überschritten. Bitte Eingabe kürzen.")
    submit = st.button("Senden", disabled=blocked)
    if submit:
        st.session_state.pop("observation_test_response", None)
        inputs = [first, second] if mode == "Loop" else [first]
        if any(not text.strip() for text in inputs):
            st.warning("Bitte alle Abfragen ausfüllen.")
        else:
            import uuid
            run_id = str(uuid.uuid4())
            outcomes = []
            for number, text in enumerate(inputs, 1):
                try:
                    with st.spinner(f"Abfrage {number}/{len(inputs)} wird gesendet …"):
                        result, warning = send_test(models[selected]["id"], models[selected]["default_model"], text, run_id=run_id, run_kind="loop" if mode == "Loop" else "single")
                    outcomes.append({"number": number, "result": result, "warning": warning})
                except ProviderTestError as exc:
                    outcomes.append({"number": number, "error": exc.details})
                    if exc.details.get("http_status") == 429:
                        st.warning("Loop wegen Anbieterlimit gestoppt; weitere Abfragen wurden nicht gesendet.")
                        break
                except Exception as exc:
                    outcomes.append({"number": number, "error": {"summary": str(exc) if isinstance(exc, ValueError) else "Lokalen Observation-Dienst prüfen."}})
                    break
            st.session_state["observation_test_response"] = outcomes
    for outcome in st.session_state.get("observation_test_response", []):
        st.markdown(f"**Abfrage {outcome['number']}**")
        if outcome.get("error"):
            st.error(outcome["error"]["summary"])
            show_metrics(outcome["error"])
            st.json(outcome["error"])
            continue
        result = outcome["result"]
        show_metrics(result)
        if outcome.get("warning"):
            st.warning(outcome["warning"])
        if "choices" in result:
            answer = result["choices"][0].get("message", {}).get("content") if result["choices"] else None
        else:
            answer = "\n".join(p.get("text", "") for c in result.get("candidates", [])
                               for p in c.get("content", {}).get("parts", []))
        if answer:
            st.text(answer)
        else:
            st.info("Keine Textantwort empfangen.")
        with st.expander("Vollständige Antwort"):
            st.json(result)
    if st.button("Schließen"):
        st.session_state["observation_test_open"] = False
        st.rerun()


def model_overview():
    config = observation_config()
    st.subheader("Modelle & Anfragegrenzen")
    st.caption("Im Observation-Test konfigurierte Modelle. Modellgrenzen aus der Dokumentation; keine Live-Kontingente und keine Verfügbarkeitsgarantie für deinen Schlüssel.")
    rows = []
    for item in config.get("llms", []):
        model = selected_model(item["id"], item["default_model"])
        limits = config.get("request_limits", {}).get(model, {})
        rows.append({"Anbieter": item["provider"], "Modell": model,
                     "Eingabegrenze (Tokens)": limits.get("input_tokens", "Nicht separat angegeben" if limits else "Unbekannt"),
                     "Kontext: Eingabe + Antwort": limits.get("context_tokens", "Nicht separat angegeben" if limits else "Unbekannt"),
                     "Max. Ausgabe (Tokens)": limits.get("output_tokens", "Unbekannt"),
                     "Antwortlimit im Test": ANSWER_TOKENS,
                     "Live-Verfügbarkeit": "Nicht geprüft",
                     "Minuten-/Tageskontingent": "Nicht verfügbar"})
    st.dataframe([{k: str(v) for k, v in row.items()} for row in rows], hide_index=True, width="stretch")
    st.caption("Das Testfeld erlaubt zusätzlich maximal 12.000 Zeichen pro Anfrage. Bei Loops gilt die Grenze für jede Anfrage einzeln.")
    for item in config.get("llms", []):
        model = selected_model(item["id"], item["default_model"])
        limits = config.get("request_limits", {}).get(model, {})
        if limits.get("source"):
            st.markdown(f"[{model}: Modell-Dokumentation]({limits['source']}) · geprüft {limits['checked']}")


def render():
    st.set_page_config(page_title="Observation", page_icon="🔎", layout="wide", initial_sidebar_state="collapsed")
    st.html("""<style>
    .stMainBlockContainer {padding-bottom: 1rem;}
    [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"]
    [data-testid="stIconMaterial"] {
        font-size: 1.45rem;
        vertical-align: -0.2em;
        background: transparent;
        color: inherit;
    }
    [class*="st-key-obs-success-"] { --obs-status-color: #10b981; }
    [class*="st-key-obs-error-"] { --obs-status-color: #f43f5e; }
    [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] span[style*="color"]:has([data-testid="stIconMaterial"]) {
        color: var(--obs-status-color, inherit) !important;
    }
    [data-testid="stExpander"] summary img {
        width: 1.35rem; height: 1.35rem; object-fit: contain;
        vertical-align: middle; background: transparent;
    }
    [data-testid="stExpander"] summary img[alt="loop-slot"],
    [data-testid="stExpander"] summary img[alt="loop-animated"] {
        min-width: 24px; max-width: 24px; width: 24px; height: 24px;
        display: inline-block;
    }
    @keyframes observation-loop-turn {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
    [data-testid="stExpander"] summary img[alt="loop-animated"] {
        animation: observation-loop-turn 2.8s linear infinite;
        transform-origin: center;
    }
    @media (prefers-reduced-motion: reduce) {
        [data-testid="stExpander"] summary img[alt="loop-animated"] {
            animation: none;
        }
    }
    [data-testid="stExpander"] summary img[alt="openai"] {
        filter: drop-shadow(0 0 1px #ffffff);
    }
    /* Each run uses the same fixed column starts, independent of text length.
       The expander itself remains full width for request/response details. */
    [class*="st-key-obs-success-"] [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p:has(img[alt^="loop-"]),
    [class*="st-key-obs-error-"] [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p:has(img[alt^="loop-"]) {
        display: grid;
        grid-template-columns: 1.5rem 12.5rem 1.6rem 7rem 1.6rem minmax(13rem, 1fr) 10rem;
        column-gap: 1.25rem;
        align-items: center;
        min-width: 57rem;
        white-space: nowrap;
    }
    [data-testid="stExpander"] summary:has(img[alt^="loop-"]) { overflow-x: auto; }
    [data-testid="stExpander"] summary p:has(img[alt^="loop-"]) code {
        background: transparent; color: inherit; padding: 0;
        font-family: inherit; font-size: inherit;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .st-key-obs-provider-filter img[alt="openai"],
    [class*="st-key-obs-model-option-"] img[alt="openai"] {
        filter: drop-shadow(0 0 1px #fff) drop-shadow(0 0 1px #fff);
    }
    [class*="st-key-obs-model-option-"] img {
        width: 1.25rem; height: 1.25rem; object-fit: contain;
        vertical-align: middle;
    }
    .st-key-obs-provider-filter img {
        width: 1.25rem; height: 1.25rem; object-fit: contain;
        vertical-align: middle;
    }
    .st-key-obs-source-filter, .st-key-obs-provider-filter {
        border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
        border-radius: 0.5rem;
        padding: 0.15rem 0.45rem;
    }
    .st-key-obs-source-filter [data-testid="stHorizontalBlock"],
    .st-key-obs-provider-filter [data-testid="stHorizontalBlock"] {
        gap: 0.35rem;
    }
    .st-key-obs-source-filter [data-testid="stColumn"]:first-child,
    .st-key-obs-provider-filter [data-testid="stColumn"]:first-child {
        flex: 0 0 auto !important;
        width: auto !important;
        min-width: max-content !important;
    }
    .st-key-obs-source-filter p, .st-key-obs-provider-filter p {
        margin-bottom: 0;
        white-space: nowrap;
    }
    .st-key-observation-toolbar h3 {
        margin: 0; padding: 0; line-height: 40px;
    }
    .st-key-observation-toolbar [data-testid="stHorizontalBlock"] {
        align-items: center;
    }
    </style>""")
    with st.container(key="observation-toolbar"):
        title_column, source_group, provider_group, refresh_column, test_column, view_column = st.columns([1.8, 1.8, 3.1, 1.3, 0.8, 3.5], vertical_alignment="center", gap="small")
    source_column = source_group
    provider_column = provider_group
    title_column.markdown("### Observation")
    if test_column.button("Test"):
        st.session_state.pop("observation_test_response", None)
        st.session_state["observation_test_open"] = True
    if st.session_state.get("observation_test_open"):
        test_dialog()
    source = source_column.selectbox("Quelle", ["Alle", "application", "chat", "evaluation"], label_visibility="collapsed",
                          format_func=lambda value: {"Alle": "Alle Quellen", "application": "Ticketanfragen", "chat": "Chat",
                                                      "evaluation": "Evaluationen"}[value])
    refresh_column.button("Aktualisieren", width="stretch")
    view = view_column.radio("Ansicht", ["Anfragen", "Modelle & Limits"], horizontal=True, label_visibility="collapsed")
    if view == "Modelle & Limits":
        model_overview()
        return
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
        st.info("Noch keine Anfragen gespeichert. Neue LLM-Anfragen erscheinen hier, wenn die Aufzeichnung aktiviert ist.")
        return
    # Only offer currently configured models. Historical observations remain intact.
    from backend.llms.registry import model_configuration
    from backend.evaluation.evaluate import load_env
    current_models = {(item["id"], item["model"])
                      for item in model_configuration(load_env())["llms"]}
    model_options = sorted({(r["provider"], r["model"]) for r in rows}
                           & current_models)
    selected = st.session_state.get("obs_model_filter")
    if selected not in model_options:
        selected = None
    def model_option_label(option):
        provider, model = option
        return f"{provider.title()} · {display_model(provider, model)}"
    current_label = "Alle Modelle" if selected is None else model_option_label(selected)
    with provider_column.popover(current_label, width="stretch"):
        if st.button("Alle Modelle", key="obs-model-all", width="stretch"):
            st.session_state["obs_model_filter"] = None
            st.rerun()
        for index, option in enumerate(model_options):
            label = model_option_label(option)
            if st.button(label, key=f"obs-model-option-{index}", width="stretch",
                         type="primary" if option == selected else "secondary"):
                st.session_state["obs_model_filter"] = option
                st.rerun()
    if selected is not None:
        rows = [r for r in rows if (r["provider"], r["model"]) == selected]
    groups = {}
    for row in rows:
        key = row.get("run_id") or row["id"]
        groups.setdefault(key, []).append(row)
    # Render only a small first page. Hundreds of nested Streamlit expanders
    # substantially delay the initial page and navigation transition.
    available_runs = len(groups)
    page_size = 20
    page_count = max(1, (available_runs + page_size - 1) // page_size)
    # Centered pagination, rather than an unlabeled numeric stepper.
    if "observation_page" not in st.session_state:
        st.session_state["observation_page"] = 1
    if st.session_state["observation_page"] > page_count:
        st.session_state["observation_page"] = page_count
    if page_count > 1:
        _, previous_col, page_col, next_col, _ = st.columns([3, 1.5, 2.3, 1.5, 3], vertical_alignment="center")
        page = st.session_state["observation_page"]
        if previous_col.button("← Zurück", key="obs-prev-page", disabled=page == 1, width="stretch"):
            st.session_state["observation_page"] = page - 1
            st.rerun()
        page_col.selectbox("Seite", range(1, page_count + 1),
                           format_func=lambda value: f"Seite {value} von {page_count}",
                           key="observation_page", label_visibility="collapsed")
        page = st.session_state["observation_page"]
        if next_col.button("Weiter →", key="obs-next-page", disabled=page == page_count, width="stretch"):
            st.session_state["observation_page"] = page + 1
            st.rerun()
    else:
        page = 1
    groups = dict(list(groups.items())[(page - 1) * page_size:page * page_size])
    rows = [row for group in groups.values() for row in group]
    pending = sum(not r["completed_at"] for r in rows)
    failed = sum(r["error_json"] is not None for r in rows)
    st.caption(f"{available_runs} Läufe insgesamt · Seite {page}/{page_count} · {len(rows)} Anfragen auf dieser Seite · {pending} ausstehend · {failed} Fehler")
    st.caption("Zeitstempel　 ·　 Dauer　 ·　 Modellname　 ·　 Kosten")
    for run_id, requests in groups.items():
        try:
            timestamp = datetime.fromisoformat(requests[0]["created_at"]).astimezone().strftime("%d.%m.%Y %H:%M:%S")
        except (ValueError, TypeError):
            timestamp = str(requests[0]["created_at"])
        label = (f"{status_icon(requests)} `{timestamp}` " + loop_marker(requests)
                 + f" `{run_duration(requests)}` " + provider_logos_markdown(requests)
                 + f" `{run_cost(requests)}`")
        with status_expander(label, requests, run_id):
            st.caption(f"Lauf-Kennung: {run_id}")
            costs = [effective_cost(r) for r in requests]
            known = [cost for cost in costs if cost is not None]
            st.caption(f"Geschätzte Standardkosten: ${sum(known):.8f} · {len(known)}/{len(costs)} Anfragen mit Kostendaten" if known else "Kosten dieses Laufs unbekannt")
            _, content = st.columns([1, 30])
            with content:
                for number, row in enumerate(requests, 1):
                    with status_expander(f"{status_icon([row])} {number}. {row['provider']} · {display_model(row['provider'], row['model'])}\u2003\u2003{run_duration([row])}\u2003\u2003{run_cost([row])}", [row], row["id"] + "-request"):
                        st.caption(f"Quelle: {row['source']} · Kennung: {row['id']} · Start: {row['created_at']}")
                        if row["completed_at"]:
                            try:
                                seconds = (datetime.fromisoformat(row["completed_at"]) -
                                           datetime.fromisoformat(row["created_at"])).total_seconds()
                                st.caption(f"Dauer: {seconds:.2f} Sekunden")
                            except (TypeError, ValueError):
                                st.caption("Dauer nicht verfügbar.")
                        show_metrics(json.loads(row["response_json"] or row["error_json"] or "{}"))
                        for title, field in (("Anfrage", "request_json"), ("Antwort", "response_json"), ("Fehler", "error_json")):
                            if row[field] is not None:
                                st.markdown(f"**{title}**")
                                try:
                                    st.json(json.loads(row[field]))
                                except (TypeError, ValueError):
                                    st.text(row[field])

if __name__ == "__main__":
    render()
