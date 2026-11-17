# VICE OVERDRIVE – Shorts-Pipeline (0 €)

YouTube `@viceoverdrive6` · TikTok `@viceoverdrive` · Budget 0 € · keine Zahlungsmethode, keine Testabos, keine Bezahl-APIs.
Nur Python-Standardbibliothek + ffmpeg. Auf dem Arbeits-Mac wird nichts installiert.

## Ablauf

1. **Radar** `python -m vo radar` – sucht Clips bei den 5 Kanälen aus `config.json`
   (montanablack88, eliasn97, trymacs, xrohat, gtasty) und in der Kategorie „Grand Theft Auto VI“
   (nur Clips mit Sprache `de`). Fasst Duplikate zusammen (gleiche Clip-ID, gleiches VOD ±30 s,
   gleicher Kanal + gleicher Titel) und sortiert nach **Zuwachs der Aufrufe seit dem letzten Check**.
   Ergebnis: `data/radar/radar-*.md`. **Nur zum Entdecken** – es wird nichts heruntergeladen.
2. **Brief** anlegen (Vorlage `briefs/BEISPIEL-eigene-aufnahme.json`): Quelldatei, Ausschnitt,
   Rechte (`own` oder `licensed` + `proof`), Thema, optional Hook, Untertitel (Liste oder .srt).
   Ohne bestätigte Rechte bricht der Schnitt ab. Twitch-Material nur mit dokumentierter Freigabe.
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

## Secrets (nur als Umgebungsvariablen / GitHub-Repository-Secrets, nie in Chat oder Repo)

| Name | Wofür | Woher (kostenlos) |
|---|---|---|
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Radar | dev.twitch.tv/console → Anwendung registrieren (Twitch-Konto mit 2FA nötig) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | YouTube-Upload | Google Cloud Console: Projekt anlegen (ohne Abrechnungskonto), „YouTube Data API v3“ aktivieren, OAuth-Client (Typ „Web“, Redirect `https://developers.google.com/oauthplayground`) anlegen; Refresh-Token im OAuth 2.0 Playground mit eigenen Client-Daten und Scope `https://www.googleapis.com/auth/youtube.upload` erzeugen – alles im Browser, keine Installation |
| `BUFFER_API_KEY` | TikTok über Buffer | publish.buffer.com/settings/api (API ist im Free-Plan enthalten) |
| `BUFFER_TIKTOK_CHANNEL_ID` | Ziel-Kanal | per API-Abfrage `channels` nach Verbinden des TikTok-Kontos |
| `VO_MEDIA_BASE_URL` | öffentliche Video-URL für Buffer | **offen**, siehe unten |

## Wichtige Grenzen der Gratis-Wege

- **YouTube API**: 10.000 Quota-Einheiten/Tag, ein Upload kostet 1.600 → max. ~6 Uploads/Tag.
  Uploads aus **nicht geprüften** API-Projekten (nach dem 28.07.2020 angelegt) bleiben gesperrt **privat**,
  bis Google das Projekt prüft (Audit, kostenlos, dauert). Bis dahin: privat hochladen, in YouTube Studio
  selbst auf öffentlich/geplant stellen.
- **Buffer Free**: 1 API-Key, 1.000 Requests/Kanal/30 Tage, kleine Warteschlange pro Kanal.
  Buffer holt Videos **nur über einen öffentlichen Link**, Datei-Upload per API gibt es nicht.
  Vor dem ersten Live-Lauf im Buffer-Konto prüfen, ob der TikTok-Kanal automatisches Veröffentlichen
  anbietet; sonst `scheduling_type` in `config.json` auf `notification` stellen (Push aufs Handy).
- **Twitch**: Clips dürfen entdeckt, aber nicht ohne Erlaubnis des Streamers weiterverwendet werden.

## GitHub Actions

- `.github/workflows/test.yml` – manuell starten (Actions → „VICE OVERDRIVE Test“ → Run workflow).
  Läuft auf `ubuntu-latest`, führt Demo, Unit-Tests und Selbsttest aus, prüft 1080×1920/H.264,
  legt die Testvideos 3 Tage als privates Artefakt ab (Name endet auf NICHT-POSTEN).
- `.github/workflows/manual-run.yml` – manueller Radar- oder Publish-Dry-Run mit Secrets.
- **Kein Zeitplan.** Actions ist nur für Entwicklung und Test vorgesehen.

## Dauerbetrieb: bewusst AUS

Gesucht war eine Laufzeit ohne hinterlegte Zahlungsmethode, die den Betrieb erlaubt und ffmpeg rendern kann. Ergebnis:

| Option | Ohne Karte? | Problem |
|---|---|---|
| GitHub Actions (Cron) | ja | laut Vorgabe nur Entwicklung/Test; GitHubs Nutzungsbedingungen erlauben Actions nur für Arbeit am Softwareprojekt, nicht als Dauer-Produktion |
| Oracle Cloud Always Free, Google Cloud, AWS, Azure | nein | Kreditkarte bei Anmeldung Pflicht |
| Google Apps Script / Cloudflare Workers (Cron) | ja | kein ffmpeg → könnte nur das Radar übernehmen, nicht den Schnitt |

Offen bis zum Dauerbetrieb:
1. Eine Laufzeit, die ohne Karte rendern darf (z. B. ein eigener, ohnehin laufender Rechner/Raspberry Pi – nicht der Arbeits-Mac).
2. Ein öffentlicher, kostenloser Ablageort für die fertigen MP4 (für Buffer).
3. Laufend eigene oder freigegebene Videodateien – das Radar liefert nur Ideen.
4. Untertitel kommen aus Brief/.srt; automatische Transkription ist nicht eingebaut.
