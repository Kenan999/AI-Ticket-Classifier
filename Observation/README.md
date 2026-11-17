# Observation

## Erster Schritt: LLM-Verzeichnis

`config.json` listet die zwei auf diesem Branch eingebundenen LLM-Anbieter: Gemini und OpenAI. Jeder Eintrag enthält Kennung, Anbieter, Standardmodell und den Namen der Umgebungsvariable für eine Modellüberschreibung. Die Anzahl ergibt sich aus der Länge der Liste `llms`.

Die Modellnamen sind die Standards aus dem Projektcode, keine Abfrage der aktuell laufenden Konfiguration. Zugangsdaten sind nicht enthalten.

Der lokale Keyword-Klassifikator ist kein LLM und wird deshalb nicht aufgeführt. DistilBERT gehört zu einem separaten Branch und ist hier nicht eingebunden.

Diese Datei ist zunächst nur ein Verzeichnis. Es gibt noch keine automatische LLM-Erkennung, Protokollierung oder Observation-Oberfläche.


## SQLite-Grundlage

Der Abschnitt `database` in `config.json` enthält Datenbanktyp und Pfad.
Relative Pfade beziehen sich auf das Projektverzeichnis.

`initialize_database()` in `database.py` legt die Datei und fehlende
Elternordner beim ausdrücklichen Aufruf an. Existiert die Datenbank bereits,
wird sie weiterverwendet; vorhandene Tabellen und Daten werden nicht gelöscht.
Importieren allein erzeugt keine Datenbank. Fehler werden an den Aufrufer
weitergegeben.

Manueller Aufruf aus dem Projektverzeichnis:

```sh
python -m Observation.database
```

Der Standardpfad liegt unter dem bereits Git-ignorierten Ordner `results/`.
Nur der separat gestartete Observation-Dienst initialisiert seine Datenbank und Tabelle automatisch. Backend und Evaluations-Dashboard sind nicht integriert. Vorhandene Daten bleiben erhalten.

## Lokaler Dienst

Start: `python -m Observation.service`. Host und Port stehen in der Config (Standard: 127.0.0.1:8510). Der Dienst erstellt seine Tabelle beim Start.

- `GET /health`: Erreichbarkeit und Datenbank prüfen.
- `POST /observations`: JSON mit `source` (application/evaluation), `provider`, `model`, `request` (Objekt). Liefert eine Kennung.
- `PATCH /observations/<id>`: `response` oder `error` zur Anfrage ergänzen. Abgeschlossene Einträge können nicht überschrieben werden.

Nur lokaler Zugriff, kein CORS. Zugangsdaten und HTTP-Header dürfen nicht gesendet werden; bekannte Credential-Felder werden zusätzlich entfernt. Freitext wird nicht automatisch auf Geheimnisse untersucht.

Backend und Evaluation senden noch keine Anfragen an diesen Dienst. Er startet separat; kein automatischer Hintergrundprozess beim Import.

## Eigenständiges Dashboard

Start: `python -m streamlit run Observation/dashboard.py --server.address 127.0.0.1 --server.port 8511`

Liest SQLite ausschließlich lesend. Zeigt die neuesten 200 Anfragen je Quelle, mit Anbieterfilter und aufklappbarer Anfrage, Antwort oder Fehlermeldung. Aktualisierung erfolgt über den Button. Ohne angebundene Aufrufer bleibt die Ansicht leer. Das Evaluation-Dashboard wird nicht verändert.


## Gruppierte Läufe
Aufrufer senden für alle Anfragen derselben Schleife dieselbe eindeutige
`run_id` beim POST mit. Ohne diese Kennung ist die Anfrage ein eigener Lauf.
Alte Einträge ohne Kennung werden ebenfalls einzeln angezeigt.
Das Dashboard zeigt aufklappbare Läufe und darunter eingerückte, aufklappbare
Anfragen. Anbieter- und Quellenfilter schränken die angezeigten Anfragen ein.
Die Integration der Aufrufer steht weiterhin aus.


## Request details and cost estimates
The standalone test records endpoint, HTTP status, safe response headers (request IDs, rate-limit values and retry-after), request/response byte sizes, configured timeout, duration, attempts and retries. Raw provider responses preserve usage, finish reasons and safety information when supplied. No authorization or cookie headers are captured.
Token usage and estimated USD standard-price cost appear per request and as a partial run sum with coverage. Rates and their source/date live in config.json; a price snapshot is saved with each new response. These are not invoices: free tiers, discounts and special tool/storage charges are not inferred. Unknown model prices or absent usage stay unknown, including failed requests; they are not treated as free. Old records remain intact and are not retrospectively priced. The direct test currently makes one attempt and no automatic retries. This does not integrate application or evaluation traffic.
