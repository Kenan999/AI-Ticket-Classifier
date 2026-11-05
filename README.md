# IHK-Projekt

Gemeinsames Projekt zum „Generative AI Expert (IHK)“.

## Termine

- 6. November 2026: Projektthema einreichen.
- 2. Dezember 2026: Schriftliche Projektarbeit abgeben.
- 8. Dezember 2026: Präsentation und Prüfung.

Termine gemäß den Kick-off-Unterlagen.

## Projektübersicht

[Öffentliche Projektseite](https://ihk-projekt.kali.sarl)

Die Projektinhalte werden Schritt für Schritt ergänzt.

## Entwicklung und technischer Stand

Stand: 5. November 2026. Auf dem Server besteht die öffentliche Projektseite derzeit aus einer einzelnen statischen HTML-Datei mit eingebettetem CSS (`public/index.html`). Für diese Seite sind kein Node.js, npm, Framework, Paketdownload oder Buildschritt erforderlich. Ein Browser genügt zum direkten Öffnen der Datei; für einen lokalen HTTP-Start wird Python 3 benötigt. Die untenstehenden Befehle wurden mit Python 3.12.3 geprüft. Git wird zum Klonen und für die Zusammenarbeit benötigt.

Das Repository enthält die statische Seite unter `public/index.html` und diese Anleitung. Nach dem Klonen kann die Seite ohne Paketinstallation lokal gestartet werden.

## Repository klonen

Das Repository ist privat; zum Klonen ist ein GitHub-Konto mit freigeschaltetem Zugriff und eingerichteter Git-Authentifizierung erforderlich. Keine Zugangsdaten in Dateien oder Clone-URLs eintragen.

```sh
git clone https://github.com/Kenan999/IHK-Projekt.git
cd IHK-Projekt
```

## Lokal starten

Im geklonten Repository:

```sh
python3 --version
python3 -m http.server 8000 --bind 127.0.0.1 --directory public
```

Dann im Browser `http://127.0.0.1:8000/` öffnen. Mit `Ctrl+C` den Server beenden. Falls Port 8000 belegt ist, einen anderen freien Port verwenden und die Browseradresse anpassen. Der Entwicklungsserver darf nur das Verzeichnis `public` ausliefern; den Repository-Root nicht als Webverzeichnis verwenden.

Für die statische Seite sind keine Umgebungsvariablen, Secrets, Datenbank oder weiteren Python-Pakete erforderlich. Der private Serverbetrieb und das private Ticketsystem gehören nicht zur lokalen Einrichtung des Teamprojekts. Deren Dateien und Daten bleiben außerhalb der Git-Veröffentlichung.

## Prüfen

Für die statische Teamseite ist derzeit keine automatisierte Testsuite im Repository vorhanden. Nach Änderungen die lokale Seite im Browser öffnen und Inhalt, schmale/breite Ansichten, Lesbarkeit sowie gegebenenfalls Links prüfen. Bei laufendem lokalen Server kann zusätzlich der HTTP-Aufruf geprüft werden:

```sh
python3 -c "import urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/'); print(r.status); assert r.status == 200"
```

Dieser HTTP-Test bestätigt die Erreichbarkeit, nicht die visuelle Darstellung. Tests des privaten Ticketsystems sind kein Nachweis für die Teamseite.

## Zusammenarbeit und Veröffentlichung

Beabsichtigter Ablauf: **Branch → Push → Pull Request → Tests und Review → Merge**.

1. Im eigenen Clone einen Arbeitsbranch von einem aktuellen `main` erstellen, zum Beispiel `git switch -c team/thema`.
2. Änderung lokal entwickeln und prüfen; zum Abschluss dieser Änderung die README an den tatsächlichen Stand anpassen.
3. Mit `git diff` und `git status` prüfen, dann ausschließlich die vorgesehenen Teamdateien gezielt stagen und committen. Keine privaten Dateien oder Secrets aufnehmen.
4. Den Arbeitsbranch mit `git push -u origin team/thema` veröffentlichen und einen Pull Request nach `main` öffnen.
5. Die verfügbaren Prüfungen und das Review im Team abschließen, danach mergen.

Entwicklung und Livebetrieb sollen getrennt bleiben: Änderungen zunächst im eigenen Clone prüfen; ein Merge nach `main` gibt die Änderung zur automatischen Live-Veröffentlichung frei. Nach einem Push auf `main` (auch durch einen PR-Merge) prüft jetzt ein serverseitiger Poller den neuen GitHub-Stand und veröffentlicht eine gültige statische Seite automatisch. Featurebranches lösen keine Veröffentlichung aus. Der Livebetrieb verwendet einen separaten Serverprozess; die lokalen Startbefehle ersetzen dessen Konfiguration nicht.

**Noch offen bzw. nicht als eingerichtet belegt:** separat erreichbare Entwicklungs-Preview, GitHub-CI-Pipeline und GitHub-Branchschutz. Eine getrennte Entwicklungsarbeitskopie ist vorhanden; sie ist keine öffentlich erreichbare Preview. Das unten beschriebene serverseitige Auto-Deployment ist eingerichtet. Der oben beschriebene Reviewablauf ist eine Arbeitsvereinbarung, keine behauptete technische Erzwingung. Weitere Infrastruktur wird durch diese Dokumentation nicht eingerichtet.

## Dokumentation aktuell halten

Bei jeder Änderung am eigentlichen IHK-Teamprojekt zum Abschluss diese README aktualisieren, insbesondere Voraussetzungen, Abhängigkeiten, Installation, Konfiguration ohne Secrets, Start, Tests und Arbeits-/Deployablauf. Ausschließlich private Ticketsystem-Arbeit ist davon ausgenommen. Ziel ist, dass jedes freigeschaltete Teammitglied den veröffentlichten Stand klonen und selbst daran entwickeln kann.

## Automatische Veröffentlichung von main

Ein serverseitiger Timer fragt GitHub etwa alle 30 Sekunden nach `main` ab. Nach einem erfolgreichen Push bzw. PR-Merge wird ausschließlich `public/` aus dem bestätigten Commit in ein separates Release übernommen. Hinzu kommen Abruf- und Prüfzeit; eine sekundengenaue oder sofortige Veröffentlichung ist nicht garantiert. Dafür muss kein GitHub-Actions-Workflow gepusht werden. Es werden keine Featurebranches veröffentlicht und keine Befehle aus dem Repository ausgeführt.

Voraussetzung ist eine vollständige statische Seite mit `public/index.html`. Erlaubt sind reguläre, nicht versteckte Dateien mit folgenden Endungen: HTML, CSS, JS, JSON, SVG, PNG, JPG/JPEG, GIF, WEBP, ICO, WOFF/WOFF2, TTF, TXT und WEBMANIFEST. Symlinks und ausführbare Dateien werden abgewiesen. Pro Release gelten maximal 2.000 Dateien, 50 MiB Gesamtgröße und 2 MiB für die HTML-Einstiegsdatei. Die Einstiegsdatei muss ein HTML-Dokument sein. Diese Minimalprüfung ist keine vollständige HTML-, Sicherheits- oder Funktionstest-Suite. Server-Backends, Paketinstallation und Builds sind nicht Bestandteil dieses Deployments.

Die saubere Deploymentkopie und aktive Live-Releases sind von Entwicklungs-Arbeitskopien und privaten Daten getrennt. Der Server benötigt weiterhin GitHub-Lesezugriff; Authentifizierung wird ausschließlich serverseitig verwaltet. Ausfälle beim Abruf oder ein fehlendes/ungültiges `public/index.html` lassen die bestehende Live-Seite unverändert.

Nach der Prüfung erfolgt ein atomarer Wechsel auf das neue Release. Ein HTTP-Test vergleicht den ausgelieferten Inhalt der Startseite mit dem Commit; bei einem Fehler wird automatisch das vorherige Release wiederhergestellt. Parallele Veröffentlichungen werden gesperrt. Der Live-Webserver liefert nur den öffentlichen Release-Inhalt aus; private Daten werden nicht übernommen.

Zur Wiederherstellung kann die Serververantwortung den Poller pausieren und ein erhaltenes vorheriges Release zurückschalten; die konkrete Betriebsanleitung bleibt privat. Ein neuer Push auf `main` kann danach erneut veröffentlichen. Es gibt bisher keine automatische Bereinigung alter Releases; Speicherbelegung muss im Betrieb geprüft werden.

Geprüft wurden kontrollierte Änderungen in einem isolierten lokalen Testrepository auf dem Server: gültiger `main`-Stand, ignorierter Featurebranch, ungültige Seite, Ausschluss privater Dateien, Serialisierung und HTTP-Rollback. Der aktive Timer und GitHub-Lesezugriff wurden ebenfalls geprüft. Für den vollständigen GitHub-zu-Live-Nachweis wird nach einem echten Push geprüft, ob der Timer genau dessen Commit als Release aktiviert und die öffentliche Domain den erwarteten Inhalt ausliefert. Ein HTTP-Test allein bestätigt keine visuelle Browserdarstellung.

## Arbeitszweig Backend

Dieser Entwicklungszweig ist für die spätere Anwendungsbackend-Entwicklung vorgesehen. Aktuell gibt es noch keine Backend-Anwendungsimplementierung, API oder festgelegte Backend-Abhängigkeiten. Die vorhandene statische Seite unter `public/` bleibt als gemeinsame Repository-Basis erhalten; ein statischer Betriebswebserver ist kein Anwendungsbackend. Architektur, Schnittstellen und konkrete Aufgaben werden erst im Team festgelegt.

Dieser Branch und `Frontend` sind Entwicklungszweige desselben Repositorys, keine getrennten Anwendungen oder Ersatz für eine spätere Verzeichnisstruktur. Änderungen gelangen nach Tests und Review per Pull Request nach `main`; ein Push auf `Backend` allein verändert die Live-Seite nicht. Private Betriebs- und Ticketsystemdateien gehören nicht in diesen Zweig.
