"""Standalone, read-only Streamlit observation dashboard."""
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
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


def loop_marker(rows):
    import base64
    path = '<path d="M7 7h10v3l4-4-4-4v3H5v6h2zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2z" fill="#8b95a5"/>' if is_loop(rows) else ""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">{path}</svg>'
    data = base64.b64encode(svg.encode()).decode()
    alt = "loop-animated" if is_loop(rows) else "loop-slot"
    return f"![{alt}](data:image/svg+xml;base64,{data})"


def provider_logos(rows):
    import base64
    logos = []
    for provider, model in sorted({(row["provider"], row["model"]) for row in rows}):
        if provider not in {"openai", "gemini"}:
            continue
        path = Path(__file__).with_name("assets") / (provider + ".svg")
        if path.is_file():
            encoded = base64.b64encode(path.read_bytes()).decode()
            safe_model = str(model).replace("`", "")
            logos.append(f"![{provider}](data:image/svg+xml;base64,{encoded}) `{safe_model}`")
    return "　".join(logos)


def run_cost(rows):
    costs = [stored_metrics(row).get("estimated_standard_cost_usd") for row in rows]
    known = [cost for cost in costs if isinstance(cost, (int, float)) and not isinstance(cost, bool)]
    if not known:
        return "Kosten: unbekannt"
    suffix = " (unvollständig)" if len(known) != len(costs) else ""
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
    if len(rows) > 1:
        return True
    for row in rows:
        try:
            request = json.loads(row["request_json"])
            if isinstance(request, dict) and request.get("_observation", {}).get("run_kind") == "loop":
                return True
        except (ValueError, TypeError, AttributeError):
            pass
    return False


@contextmanager
def status_expander(label, rows, key):
    state = "error" if any(r["error_json"] is not None for r in rows) else "success"
    kind = "loop" if is_loop(rows) else "single"
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



def safe_response_headers(headers):
    allowed = {"x-request-id", "request-id", "retry-after", "openai-processing-ms"}
    return {k.lower(): v for k, v in (headers.items() if headers else [])
            if k.lower() in allowed or k.lower().startswith("x-ratelimit-")}


def request_metrics(provider, model, response, elapsed, transport, config):
    usage = response.get("usage", {}) if provider == "openai" else response.get("usageMetadata", {})
    inp = usage.get("prompt_tokens" if provider == "openai" else "promptTokenCount")
    out = usage.get("completion_tokens" if provider == "openai" else "candidatesTokenCount")
    cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0) if provider == "openai" else usage.get("cachedContentTokenCount", 0)
    reasoning = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0) if provider == "openai" else usage.get("thoughtsTokenCount", 0)
    billed_output = out + reasoning if provider == "gemini" and out is not None else out
    rates = config.get("pricing", {}).get(model)
    cost = None
    if rates and inp is not None and billed_output is not None:
        cost = (max(0, inp-cached)*rates["input"] + cached*rates["cached_input"] + billed_output*rates["output"])/1_000_000
    return {**transport, "provider": provider, "requested_model": model,
            "returned_model": response.get("model", response.get("modelVersion")),
            "response_id": response.get("id", response.get("responseId")),
            "duration_seconds": round(elapsed, 4), "attempts": 1, "retries": 0,
            "input_tokens": inp, "output_tokens": out, "cached_input_tokens": cached,
            "reasoning_tokens": reasoning, "total_tokens": usage.get("total_tokens", usage.get("totalTokenCount")),
            "estimated_standard_cost_usd": cost, "pricing_snapshot": rates,
            "cost_note": "Schätzung zum Standardtarif, keine Rechnung; Free Tier, Rabatte und Sonderkosten nicht berücksichtigt. Unbekannte Werte bleiben leer.",
            "finish_reasons": [c.get("finish_reason", c.get("finishReason")) for c in response.get("choices", response.get("candidates", []))],
            "usage_raw": usage}


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


def send_test(provider, model, text, run_id=None, run_kind="single"):
    """Send one explicit user-triggered request and record it via the local service."""
    import os
    from urllib.request import Request, urlopen
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    env = dict(os.environ)
    env_path = ROOT / "backend" / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key.strip() in {"OPENAI_API_KEY", "GEMINI_API_KEY", "OPENAI_MODEL", "GEMINI_MODEL"}:
                    env.setdefault(key.strip(), value.strip().strip("\"'"))
    key = env.get(provider.upper() + "_API_KEY", "").strip()
    if not key:
        raise ValueError("Für diesen Anbieter ist kein API-Schlüssel konfiguriert.")
    model = model if provider == "gemini" else env.get(provider.upper() + "_MODEL", model)
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", model):
        raise ValueError("Ungültiger Modellname.")
    if provider == "openai":
        url = "https://api.openai.com/v1/chat/completions"
        payload = {"model": model, "messages": [{"role": "user", "content": text}], "max_completion_tokens": 1024}
        headers = {"Authorization": "Bearer " + key}
    elif provider == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
        payload = {"contents": [{"role": "user", "parts": [{"text": text}]}],
                   "generationConfig": {"maxOutputTokens": 1024}}
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
                 "model": model, "request": {**payload, "_observation": {"run_kind": run_kind}}, "run_id": run_id or str(uuid.uuid4())})["id"]
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
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    models = config.get("llms", [])
    if not models:
        st.info("Keine LLMs konfiguriert.")
        return
    st.caption("Ein direkter Modelltest, ohne Klassifizierungs-Prompt. Senden nutzt die API und speichert Anfrage und Antwort lokal.")
    mode = st.radio("Testart", ["Einzel", "Loop"], horizontal=True)
    with st.form("observation_test"):
        selected = st.selectbox("LLM", range(len(models)),
            format_func=lambda i: models[i]["provider"] + " · " + models[i]["default_model"])
        first = st.text_area("Abfrage 1", max_chars=12000)
        second = st.text_area("Abfrage 2", max_chars=12000) if mode == "Loop" else None
        submit = st.form_submit_button("Senden")
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


def render():
    st.set_page_config(page_title="Observation", page_icon="🔎", layout="wide")
    st.html("""<style>
    .stMainBlockContainer {padding-top: 4rem; padding-bottom: 1rem;}
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
    .obs-table-header,
    [data-testid="stExpander"] summary p:has(img[alt^="loop-"]) {
        display: grid;
        grid-template-columns: 1.5rem 17rem 1.5rem 6rem 1.5rem 11rem 10rem;
        column-gap: 1rem;
        align-items: center;
        width: 100%;
    }
    .obs-table-header {
        padding: 0.5rem 1rem 0.5rem 2.3rem;
        font-weight: 600;
        color: var(--text-color);
        opacity: 0.75;
    }
    [data-testid="stExpander"] summary p:has(img[alt^="loop-"]) code {
        background: transparent; color: inherit; padding: 0;
        font-family: inherit; font-size: inherit;
        font-variant-numeric: tabular-nums;
    }
    [data-testid="stExpander"] summary:has(img[alt^="loop-"]) {
        overflow-x: auto;
    }
    .st-key-observation-toolbar {
        position: fixed;
        top: 0.5rem;
        left: 2rem;
        right: 6rem;
        width: auto;
        z-index: 1000001;
        background: transparent;
    }
    .st-key-observation-toolbar h3 {
        margin: 0; padding: 0; line-height: 40px;
    }
    .st-key-observation-toolbar [data-testid="stHorizontalBlock"] {
        align-items: center;
    }
    </style>""")
    with st.container(key="observation-toolbar"):
        title_column, source_column, provider_column, refresh_column, test_column = st.columns([3, 2, 2, 1.4, 1], vertical_alignment="center")
    title_column.markdown("### Observation")
    if test_column.button("Test"):
        st.session_state.pop("observation_test_response", None)
        st.session_state["observation_test_open"] = True
    if st.session_state.get("observation_test_open"):
        test_dialog()
    source = source_column.selectbox("Quelle", ["Alle", "application", "evaluation"], label_visibility="collapsed",
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
    provider = provider_column.selectbox("Anbieter", ["Alle"] + sorted({r["provider"] for r in rows}), label_visibility="collapsed")
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
    st.html('<div class="obs-table-header"><span></span><span>Zeitstempel</span><span></span><span>Dauer</span><span></span><span>Modellname</span><span>Kosten</span></div>')
    for run_id, requests in groups.items():
        try:
            timestamp = datetime.fromisoformat(requests[0]["created_at"]).astimezone().strftime("%d.%m.%Y\u2003\u2003\u2003%H:%M:%S")
        except (ValueError, TypeError):
            timestamp = str(requests[0]["created_at"])
        label = f"{status_icon(requests)} `{timestamp}` " + loop_marker(requests)
        label += f" `{run_duration(requests)}` " + provider_logos(requests)
        label += f" `{run_cost(requests)}`"
        with status_expander(label, requests, run_id):
            st.caption(f"Lauf-Kennung: {run_id}")
            costs = [stored_metrics(r).get("estimated_standard_cost_usd") for r in requests]
            known = [cost for cost in costs if cost is not None]
            st.caption(f"Geschätzte Standardkosten: ${sum(known):.8f} · {len(known)}/{len(costs)} Anfragen mit Kostendaten" if known else "Kosten dieses Laufs unbekannt")
            _, content = st.columns([1, 30])
            with content:
                for number, row in enumerate(requests, 1):
                    with status_expander(f"{status_icon([row])} {number}. {row['provider']} · {row['model']}\u2003\u2003{run_duration([row])}\u2003\u2003{run_cost([row])}", [row], row["id"] + "-request"):
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
