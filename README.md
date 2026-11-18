# VICE OVERDRIVE – Shorts-Pipeline (0 €)

YouTube `@viceoverdrive6` · TikTok `@viceoverdrive` · Budget 0 € · keine Zahlungsmethode, keine Testabos, keine Bezahl-APIs.
Python-Standardbibliothek + ffmpeg, für automatische Radar-Downloads zusätzlich yt-dlp. Auf dem Arbeits-Mac wird nichts installiert.

## Ablauf

1. **Radar** `python -m vo radar` – sucht Clips **nur** bei den Streamern der Allowlist
   (`config.json` → `clip_allowlist`, derzeit montanablack88, eligella, xrohat, xqc, ishowspeed) und behält mit
   `gta_filter` nur Clips aus „Grand Theft Auto V“ (inkl. GTA RP) und „Grand Theft Auto VI“.
   Andere Kanäle und Spiele fallen raus. Zusätzlich durchsucht es die YouTube-Kanäle (`youtube_handle`)
   der Streamer nach neuen GTA-Videos (Titel/Beschreibung/Tags), nur lesend über die YouTube Data API
   (~3 Einheiten pro Kanal, kein teures search.list). Braucht das Secret `YT_API_KEY` (der Upload-Zugang darf nicht lesen); ohne Schlüssel wird YouTube übersprungen.
   Kick wird nicht durchsucht. Logins, die Twitch nicht kennt, stehen oben im Bericht.
   Fasst Duplikate zusammen (gleiche Clip-ID, gleiches VOD ±30 s,
   gleicher Kanal + gleicher Titel) und sortiert nach **Zuwachs der Aufrufe seit dem letzten Check**.
   Ergebnis: `data/radar/radar-*.md`. Der Befehl `radar` selbst lädt nichts herunter.
2. **Brief** anlegen (Vorlage `briefs/BEISPIEL-eigene-aufnahme.json`): Quelldatei, Ausschnitt,
   Rechte (`own` oder `licensed` + `proof`), Thema, optional Hook, Untertitel (Liste oder .srt).
   Ohne bestätigte Rechte bricht der Schnitt ab. Twitch-Material nur mit dokumentierter Freigabe.
   Für Clips aus einem Clipper-Programm: Vorlage `briefs/BEISPIEL-clipper-programm.json` mit
   `"streamer": "<twitch_login>"` und `rights.type = "clipper_program"`. Geschnitten wird nur, wenn der
   Streamer aktiv in der Allowlist steht **und** dort ein `proof` eingetragen ist (z. B. VOD-Link mit
   Zeitstempel der Ansage oder Link zu den Programmregeln). Name + Twitch-Kanal und die
   `required_tags` des Programms kommen automatisch in YouTube-Beschreibung und TikTok-Caption.
3. **Schnitt** `python -m vo make briefs/<datei>.json` → `data/shorts/<id>/short.mp4`
   (1080×1920, H.264/AAC, 30 fps, max. 59 s, unscharfer Hintergrund, Hook oben, deutsche Untertitel
   eingebrannt) plus getrennte `youtube.txt` (Titel mit #Shorts, Beschreibung, Tags) und `tiktok.txt` (Caption + Hashtags).
4. **Gesammelte Freigabe** `python -m vo batch` → `data/approvals/batch-*.json`.
   Pro Short und Plattform `"approved": true` setzen.
5. **Veröffentlichen** `python -m vo publish youtube` bzw. `tiktok` = **Dry-Run** (zeigt nur, was gesendet würde).
   Erst `--live` sendet wirklich, und nur freigegebene, nicht-synthetische Shorts.
   YouTube lädt standardmäßig als **privat** hoch. Synthetische Tests sind immer gesperrt.

Test: `python -m vo selftest` (synthetisch, offline) und `python -m unittest discover -s tests`.
Original-Demo: `python3 VICE-OVERDRIVE-0EUR.py` (unverändert übernommen).

## Radar-Treffer automatisch schneiden

- In **Actions → VICE OVERDRIVE manueller Lauf → Run workflow** den Schritt **radar-clips** wählen.
  Der Befehl `python -m vo radar-clips --limit 3` startet Radar und Schnitt direkt hintereinander.
  Standard sind bis zu drei Downloads in Radar-Reihenfolge. `radar` bleibt als separate Vorschau verfügbar.
- **Twitch:** Download nur für aktive Allowlist-Kanäle mit `proof`. **YouTube:** Treffer bleiben im
  Radar. Für den direkten Download zusätzlich `youtube_download_proof` beim jeweiligen Streamer
  eintragen, falls eine schriftliche Download-Genehmigung von YouTube vorliegt
  (siehe [YouTube API Developer Policies, Abschnitt III.E.1](https://developers.google.com/youtube/terms/developer-policies#e-handling-youtube-data-and-content)).
  Der Streamer-Beleg allein ersetzt diese nicht. Alternativ kann eine vom Creator bereitgestellte
  Videodatei über den bestehenden manuellen Brief mit passendem Rechtebeleg verarbeitet werden.
- Der Short nutzt die ersten höchstens 59 Sekunden (1080×1920, H.264/AAC). Er bekommt einen Hook
  aus dem Clip-Titel, aber **keine automatisch transkribierten Untertitel**. Name, voller Kanal-Link
  und Pflicht-Tags stehen in den plattformspezifischen Texten.
- Der Lauf räumt temporäre Downloads auf und liefert fertige MP4s, Captions und einen
  **noch nicht freigegebenen** Batch als GitHub-Artefakt. Die Zusammenfassung
  `data/radar/radar-clips-result.json` nennt übersprungene und fehlgeschlagene Treffer.
  Ein nicht erreichbarer Clip stoppt die übrigen Downloads nicht. YouTube kann Downloads von
  Cloud-Runnern ablehnen. Dieser Lauf verwendet keine Cookies, Proxies oder bezahlten Dienste.
- Die Übergabe an `vo.publish` prüft **TikTok-Inbox und YouTube Shorts im Dry-Run**.
  Der Lauf lädt zu keiner Videoplattform hoch. Für einen echten TikTok-Entwurf oder YouTube-Upload gelten weiterhin
  die separate Freigabe und der explizite `--live`-Befehl für die jeweilige Plattform.

## Autopilot auf GitHub Actions (Dauerbetrieb)

Workflow „VICE OVERDRIVE Autopilot“ (`.github/workflows/autopilot.yml`) läuft stündlich (Minute 7):
Radar → Download → Schnitt → bis zu 4 YouTube-Uploads pro Durchgang (YouTube-API: höchstens 100 Uploads/Tag)
und TikTok-Inbox-Entwürfe (TikTok: höchstens 5 offene Entwürfe in 24 Stunden, fertig posten in der App).
Nichts wird auf einem eigenen Rechner gespeichert. Der Zustand gegen Doppel-Uploads liegt im Actions-Cache
(ohne Videos und ohne TikTok-Token). Sichtbarkeit per Repo-Variable `VO_YOUTUBE_MODE`
(`public` Standard, `private`, `unlisted`, `off`), TikTok aus mit `VO_TIKTOK_INBOX=false`.
Stoppen: Actions → „VICE OVERDRIVE Autopilot“ → „…“ → Disable workflow.
Ein privater Probelauf: Workflow „manueller Lauf“ → `autopilot-privat-test`.
Ungefähr 4–5 Minuten pro Clip. Deshalb ist das Repo öffentlich (unbegrenzte Actions-Minuten).

## Lokaler Autopilot (privater Rechner, nicht auf GitHub Actions)

Der Autopilot hat getrennte Zuständigkeiten:

1. **Clip-Agent:** Twitch/YouTube-Radar, belegte Allowlist und Abgleich auf bereits verarbeitete Clip-IDs oder VOD-Ausschnitte. Vorhandene Quelle-Rechtefilter bleiben aktiv.
2. **Schnitt-Agent:** FFmpeg rendert 1080×1920 mit höchstens 60 Sekunden.
3. **Beschreibungs-Agent:** Entnimmt der **fertigen** MP4 fünf Frames. Ein lokales Ollama-Bildmodell schreibt einen konkreten deutschen Hook, eine Beobachtung und eine passende Community-Frage. Keine Bilddaten gehen an einen KI-Cloud-Dienst. Audio wird nicht transkribiert.
4. **Hashtag-Agent:** Bestätigt GTA V oder GTA VI anhand der Radar-Quelle und wählt zum erkannten Szenentyp passende Tags. Kein `#GTA6` für GTA-V-Clips. Pflicht-Tags, Streamer-Name und Kanal-Link bleiben erhalten.
5. **Upload-Agent:** Sendet maximal einen passenden Short pro Stunde über die offizielle YouTube-API. Nur mit ausdrücklich gewählter Sichtbarkeit und geprüftem Zielkanal. Unsichere Uploads werden nicht blind wiederholt. TikTok kann separat per offizieller Inbox-API einen Entwurf empfangen. Die Caption liegt lokal; die Inbox-API setzt sie nicht und veröffentlicht nichts.

### Start auf deinem privaten PC

- Repo auf dem privaten Rechner auschecken. Benötigt Python 3.10+, FFmpeg/ffprobe, yt-dlp und Ollama.
  `python -m pip install "yt-dlp[default]"` installiert den Downloader in deiner Python-Umgebung.
  Für direkte, genehmigte YouTube-Downloads zusätzlich Node 22+ installieren.
- Lokales Ollama starten und einmal `ollama pull qwen3-vl:4b` ausführen. Je nach Rechner
  ist `qwen3-vl:2b` die kleinere Alternative (`--model qwen3-vl:2b`).
- Lege optional lokal `data/autopilot.env` mit je einer Zeile `NAME=WERT` an
  (Twitch-Zugang und optional `YT_API_KEY` für das Radar). Für YouTube-Uploads zusätzlich
  `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
  Der Refresh-Token muss für **@viceoverdrive6** erzeugt sein und für diesen Autopilot
  `https://www.googleapis.com/auth/youtube.upload` sowie `https://www.googleapis.com/auth/youtube.readonly`
  umfassen, damit der Uploader den Zielkanal vor dem Upload prüfen kann. Ein reiner Upload-Token
  garantiert die Kontoprüfung nicht. Die Datei unter `data/` bleibt lokal und wird von Git ignoriert.

Erster Lauf ohne Upload:

```sh
python -m vo autopilot --env-file data/autopilot.env
```

### Autopilot ohne Ollama

Mit `--text-source files` erzeugt der bestehende Schnitt-Schritt Texte aus Radar-Titel,
bestätigter Spielkategorie und Streamer-Quellenangabe. Der Upload-Schritt liest
`youtube.txt` (erste Zeile Titel, danach Beschreibung) und `tiktok.txt` (Caption)
aus demselben Short-Ordner. Vorhandene Texte können auch von einem anderen Texter
stammen. Fehlen Texte, Pflicht-Tags oder die Quelle, wird der Clip übersprungen.
Dieser Modus schaut den Bildinhalt nicht an und benötigt weder Ollama noch einen KI-API-Key.

Automatische Beschreibung: ungefähr 20–30 Wörter mit Bezug zum Titel oder zur erkannten Szene, ohne doppelte Titelzeile und ohne Standardfrage. YouTube erhält bis zu acht passende Hashtags. In der TikTok-Caption stehen höchstens fünf Hashtags, Pflicht-Tags und Quellenzeile bleiben erhalten. [Neue Captions für den Export 01–11](docs/tiktok-captions-01-11.md).

```sh
python -m vo autopilot --text-source files --youtube off --env-file data/autopilot.env
```

`--watch` führt den lokalen Lauf stündlich aus. YouTube übernimmt Titel und
Beschreibung beim ausdrücklich aktivierten Upload automatisch. TikToks Inbox
überträgt nur das Video. Die vorbereitete Caption aus `tiktok.txt` wird in
TikTok beim Fertigstellen des Posts eingefügt.

Öffentliches Posten auf YouTube **erst bewusst einschalten**:

```sh
python -m vo autopilot --watch --youtube public --env-file data/autopilot.env
```

Mit `--tiktok-inbox` wird derselbe fertige Clip zusätzlich an TikToks Inbox geschickt.
Dafür lokal einen **frischen** `TIKTOK_REFRESH_TOKEN`, `TIKTOK_CLIENT_KEY` und
`TIKTOK_CLIENT_SECRET` hinterlegen. TikTok muss `video.upload` erlaubt haben.
Bei einem reinen Inbox-Token zusätzlich `TIKTOK_OPEN_ID` aus der OAuth-Antwort des eigenen
Kontos verwenden. Bestehende Tokens mit `video.publish` können das Konto alternativ
über den Creator-Info-Endpunkt bestätigen. Die App veröffentlicht dadurch nichts direkt.
Rotierte Refresh-Tokens bleiben in `data/autopilot/state/tiktok-token.json` auf dem privaten Rechner.
TikTok begrenzt offene Inbox-Uploads. Bei abgewiesenem Inbox-Upload prüft der nächste Lauf erneut,
bei einem unklaren Übertragungsstatus wird derselbe Clip nicht blind doppelt gesendet.

Statt `public` gibt es `private`, `unlisted` und `off` (Standard). `--watch` startet den
ersten Durchgang sofort und prüft danach stündlich. Die Sperre im lokalen Zustand verhindert
einen verfrühten Upload nach einem Neustart. Der Rechner und Ollama müssen dabei laufen.
Auf Windows startet `start-autopilot-windows.cmd` nach Einrichtung der obigen Python-Umgebung
und `data/autopilot.env` den Stundenlauf ohne Upload. Verwende
`start-autopilot-windows.cmd public` nur nach erfolgreichem Test und bewusster Upload-Freigabe.
Mit `start-autopilot-windows.cmd public inbox` wird zusätzlich TikToks Inbox aktiviert.
Für automatischen Start nach der Windows-Anmeldung kannst du die CMD-Datei in die Aufgabenplanung
eintragen (Arbeitsordner = Repo-Ordner). Führe nur eine Instanz pro Datenordner aus.

Bei unklarer Szene, widersprüchlicher Spielangabe, fehlendem Beleg oder wiederholtem Beschreibungstext
wird kein Upload ausgelöst. Es gibt also nicht zwangsläufig 24 Uploads pro Tag.
Der Autopilot löscht bei jedem Lauf seine eigenen `short.mp4` ab zwei Stunden Dateialter
aus `data/autopilot/shorts/`. Quellvideos, andere MP4s, Beschreibungen, Manifeste und der
Upload-Verlauf bleiben erhalten. Die Bereinigung ändert keine bereits hochgeladenen YouTube-Videos.
Shorts und Texte liegen in `data/autopilot/shorts/`, letzter Status in
`data/autopilot/state/last-run.json`. Erst ein Ergebnis `youtube_sent` mit Video-ID ist ein bestätigter Upload.
Mit `--youtube off` wird nicht auf YouTube zugegriffen, um etwas zu senden. Es fallen keine Kosten für
die KI-API an, weil das Modell lokal läuft.

## Secrets (nur als Umgebungsvariablen / GitHub-Repository-Secrets, nie in Chat oder Repo)

| Name | Wofür | Woher (kostenlos) |
|---|---|---|
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Radar | dev.twitch.tv/console → Anwendung registrieren (Twitch-Konto mit 2FA nötig) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | YouTube-Upload | Google Cloud Console: Projekt anlegen (ohne Abrechnungskonto), „YouTube Data API v3“ aktivieren, OAuth-Client (Typ „Web“, Redirect `https://developers.google.com/oauthplayground`) anlegen; Refresh-Token im OAuth 2.0 Playground mit eigenen Client-Daten und Scopes `https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly` erzeugen (beim Login den Kanal @viceoverdrive6 wählen; prüfen mit Workflow „manueller Lauf“ → `youtube-check`) – alles im Browser, keine Installation |
| `YT_API_KEY` | Radar auf YouTube (nur lesen) | Google Cloud Console, Projekt vice-overdrive → APIs & Dienste → Anmeldedaten → „Anmeldedaten erstellen“ → API-Schlüssel; auf „YouTube Data API v3“ beschränken. Kostenlos, keine Abrechnung nötig |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | TikTok-Upload | developers.tiktok.com → App „vice-overdrive“ → Produkte *Login Kit* + *Content Posting API*, Scopes `user.info.basic`, `video.upload`, `video.publish` |
| `TIKTOK_REFRESH_TOKEN` | TikTok-Upload | über `site/callback.html` (Anmelden) + PowerShell-Befehl, den die Seite anzeigt – nichts installieren, gilt 365 Tage |

## Wichtige Grenzen der Gratis-Wege

- **YouTube API**: Suche und Upload haben eigene Projektkontingente. Die tatsächlich verfügbaren
  Werte stehen in der Google Cloud Console. Der Autopilot setzt Sichtbarkeit ausdrücklich und
  nutzt standardmäßig keinen Upload. Der Kontostatus kann weiterhin zusätzliche Grenzen setzen.
- **TikTok Content Posting API** (kostenlos, offiziell, kein Drittanbieter):
  - Modus `inbox` (Standard): Das Video landet als Benachrichtigung/Entwurf in der TikTok-App,
    du tippst dort Caption (aus `tiktok.txt`) ein und postest selbst. Max. 5 offene Uploads pro 24 h.
  - Modus `direct`: TikTok veröffentlicht direkt mit Caption. Solange TikTok die App nicht geprüft hat (Audit),
    ist jeder Post nur für dich sichtbar (`SELF_ONLY`) **und das Konto muss auf privat stehen**.
  - Benötigt öffentliche Seiten für die App-Anmeldung: `site/` (Start, Datenschutz, Nutzungsbedingungen, Callback).
- **Twitch**: Clips dürfen entdeckt, aber nicht ohne Erlaubnis des Streamers weiterverwendet werden.
  Clipper-Programme zahlen meist nur für **angemeldete** Konten und verlangen oft einen Pflicht-Tag
  oder ein bestimmtes @ in der Caption. Regeln stehen meist im Discord des Streamers
  (Kanäle wie `clip-program`) oder auf einer Clipping-Plattform – dort anmelden und die Regeln in
  `notes`/`required_tags` übernehmen.

## GitHub Actions

- `.github/workflows/test.yml` – für PRs nach `main` oder manuell. Testet offline ohne Secrets.
  Keine Testvideos als Artefakte, keine Uploads zu Videoplattformen.
- `.github/workflows/manual-run.yml` – manueller Radar, Radar-Schnitt oder Dry-Run.
  Standard-Runner im enthaltenen GitHub-Actions-Kontingent nutzen. Für 0 € Mehrkosten
  die Ausgabengrenze bei 0 € belassen, falls Abrechnung eingerichtet ist.
- **Kein Zeitplan.** Actions ist nur für Entwicklung und Test vorgesehen.

## Dauerbetrieb: privat und lokal

Der lokale Autopilot ist im Repo verfügbar, aber wird nicht automatisch auf einem Gerät installiert.

| Option | Ohne Karte? | Problem |
|---|---|---|
| GitHub Actions (Cron) | ja | laut Vorgabe nur Entwicklung/Test; GitHubs Nutzungsbedingungen erlauben Actions nur für Arbeit am Softwareprojekt, nicht als Dauer-Produktion |
| Oracle Cloud Always Free, Google Cloud, AWS, Azure | nein | Kreditkarte bei Anmeldung Pflicht |
| Google Apps Script / Cloudflare Workers (Cron) | ja | kein ffmpeg → könnte nur das Radar übernehmen, nicht den Schnitt |

Für den Start den privaten Rechner wie oben einrichten. Die lokale Bildanalyse erstellt Texte,
keine Audiotranskription. Untertitel kommen weiterhin manuell aus Brief oder .srt.
