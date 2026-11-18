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

## Secrets (nur als Umgebungsvariablen / GitHub-Repository-Secrets, nie in Chat oder Repo)

| Name | Wofür | Woher (kostenlos) |
|---|---|---|
| `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Radar | dev.twitch.tv/console → Anwendung registrieren (Twitch-Konto mit 2FA nötig) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | YouTube-Upload | Google Cloud Console: Projekt anlegen (ohne Abrechnungskonto), „YouTube Data API v3“ aktivieren, OAuth-Client (Typ „Web“, Redirect `https://developers.google.com/oauthplayground`) anlegen; Refresh-Token im OAuth 2.0 Playground mit eigenen Client-Daten und Scope `https://www.googleapis.com/auth/youtube.upload` erzeugen – alles im Browser, keine Installation |
| `YT_API_KEY` | Radar auf YouTube (nur lesen) | Google Cloud Console, Projekt vice-overdrive → APIs & Dienste → Anmeldedaten → „Anmeldedaten erstellen“ → API-Schlüssel; auf „YouTube Data API v3“ beschränken. Kostenlos, keine Abrechnung nötig |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | TikTok-Upload | developers.tiktok.com → App „vice-overdrive“ → Produkte *Login Kit* + *Content Posting API*, Scopes `user.info.basic`, `video.upload`, `video.publish` |
| `TIKTOK_REFRESH_TOKEN` | TikTok-Upload | über `site/callback.html` (Anmelden) + PowerShell-Befehl, den die Seite anzeigt – nichts installieren, gilt 365 Tage |

## Wichtige Grenzen der Gratis-Wege

- **YouTube API**: 10.000 Quota-Einheiten/Tag, ein Upload kostet 1.600 → max. ~6 Uploads/Tag.
  Uploads aus **nicht geprüften** API-Projekten (nach dem 28.07.2020 angelegt) bleiben gesperrt **privat**,
  bis Google das Projekt prüft (Audit, kostenlos, dauert). Bis dahin: privat hochladen, in YouTube Studio
  selbst auf öffentlich/geplant stellen.
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

## Dauerbetrieb: bewusst AUS

Gesucht war eine Laufzeit ohne hinterlegte Zahlungsmethode, die den Betrieb erlaubt und ffmpeg rendern kann. Ergebnis:

| Option | Ohne Karte? | Problem |
|---|---|---|
| GitHub Actions (Cron) | ja | laut Vorgabe nur Entwicklung/Test; GitHubs Nutzungsbedingungen erlauben Actions nur für Arbeit am Softwareprojekt, nicht als Dauer-Produktion |
| Oracle Cloud Always Free, Google Cloud, AWS, Azure | nein | Kreditkarte bei Anmeldung Pflicht |
| Google Apps Script / Cloudflare Workers (Cron) | ja | kein ffmpeg → könnte nur das Radar übernehmen, nicht den Schnitt |

Offen bis zum Dauerbetrieb:
1. Eine Laufzeit, die ohne Karte rendern darf (z. B. ein eigener, ohnehin laufender Rechner/Raspberry Pi – nicht der Arbeits-Mac).
2. Freigegebene Quellen für regelmäßige Radar-Schnitte.
3. Untertitel kommen aus Brief/.srt; automatische Transkription ist nicht eingebaut.
