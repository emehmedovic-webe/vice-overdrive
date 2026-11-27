# Übergabe VICE OVERDRIVE TikTok-Clips (Stand 2026-11-26)

Alle Regeln, mit denen die Clips zuletzt erstellt wurden. Ergänzt `CLAUDE.md` und `docs/TIKTOK_CONTENT_SAFETY.md`.

## Ablauf
1. **Zuerst VODs**, dann Twitch-Clips (siehe `sourcing` in `config.json`).
   - VODs: Workflow `vod.yml` (Inputs `logins`, `vods` 2–3, `per_vod` 4–6). Ergebnis: Release `vod-momente-<stamp>` mit 45-s-Rohmomenten (`_roh/source.mp4`, `_roh/words.json`, `info.json`, `MOMENTE.md`).
   - Clips: Workflow `export.yml` (`all_recent`, `all_time`, `any_game`, `logins`, `limit`, `per_streamer`, `redo`). Ergebnis: Release `tiktok-export-<stamp>`.
   - Beide Workflows teilen sich eine Concurrency-Gruppe. Einen neuen Lauf erst starten, wenn der vorige fertig ist, sonst wird ein wartender Lauf abgebrochen.
2. Rohmaterial ansehen (Kontaktabzug per ffmpeg) und nur wirklich starke Momente nehmen.
3. Pro Clip eine `edit.json` schreiben und `python3 -m vo compose <ordner>` ausführen. Das erzeugt `video.mp4` und `caption.txt`.
4. Ausliefern (siehe unten). Vorher mit `docs/GEPOSTET.md` abgleichen, damit **nie etwas doppelt** geliefert wird.

## Streamer (Priorität)
1. Eli (`eligella`), Willy (`niklaswilson`), Sidney (`sidneyeweka`): jedes Spiel erlaubt (auch FC/FIFA), nur lustige oder starke Momente.
2. Danach Rohat (`xrohat`) und Trymacs (`trymacs`).
3. **Keine Monte-Clips mehr** (`montanablack88` ist auf active=false).

Rechtsgrundlage: Enis' Bestätigung der mündlichen Stream-Freigabe (`creator_confirmation` in `config.json`).

## Format (Stil D, von Enis am 2026-11-26 11:17 gewählt)
- Facecam oben (1080x750, Streamer immer komplett sichtbar), Gameplay unten.
- Überschrift-Box auf der Naht: ein wahrer Satz mit Streamer-Name. **Keine Emojis im Bild** (libass zeigt sie als Kästchen; `_esc` entfernt sie automatisch).
- Wort-für-Wort-Untertitel des exakten Wortlauts (unklare Whisper-Wörter in `_roh/words.json` entfernen, nichts erfinden).
- **Kein Hook, keine Text-Einblendungen mitten im Clip** (Bubbles sind im Code abgeschaltet; sie verdecken Gameplay).
- **Schimpfwörter zensiert**: Anfangsbuchstabe + Sternchen („S******“), automatisch in Untertiteln, Überschrift, Hook und Caption (`vo.split_render.censor`).
- Der Clip startet direkt am bzw. kurz vor dem Höhepunkt. Originalton, keine Bewegungseffekte, kein Wasserzeichen, Supercar-Outro.
- Länge 12–30 s (höchstens 60 s). Kein Sprachkommentar.
- `head_style`: **`dark` = D1 ist Standard** (von Enis am 2026-11-26 abends gewählt: schwarze Box, pinker Rahmen, Name pink). Weitere: `white`, `light` (weiße Box, pinker Rahmen), `clean` (ohne Box, Kontur, Name gelb).

Beispiel `edit.json`:
```json
{"streamer": "xrohat", "start": 14.0, "end": 45.0,
 "headline": "Rohat rammt einen SUV – der hebt fast ab",
 "head_style": "dark",
 "caption": "Rohat rammt in GTA 6 einen SUV, der fast umkippt, und regt sich danach über den Verkehr auf.",
 "tags": ["#gta6", "#xrohat", "#verkehr"]}
```
Optional: `facecam` {x,y,w,h} und `game_x` (im 1920x1080-Bild), wenn das Layout vom Standard in `config.json` abweicht (z. B. FC-Streams), `blur` für Chat-Namen, `subtitles: false`.
Nach `python -m vo compose <ordner>` an die letzte Caption-Zeile ` #fyp #foryou #foryoupage #fy` anhängen.

## Caption (.txt)
- Zeile 1: ein wahrer Satz. Zeile 2: leer. Zeile 3: Hashtags.
- Hashtags: `#gta6` (bzw. Spiel-Tag) `#<streamer>` `#<thema>` `#fyp #foryou #foryoupage #fy`.
- **Kein @-Erwähnen des Streamers.**
- Reines ASCII, UTF-8 ohne BOM. Hinweis: TikTok macht eingefügte Hashtags nicht fett. Entweder selbst tippen oder nach dem Einfügen hinter jedem Hashtag ein Leerzeichen setzen.
- Keine URLs, keine Quellenangaben, keine Fragen.

## Lieferung
- Ein Ordner pro Tag: `~/Downloads/CLIPS_<JJJJ-MM-TT>/`. Am 2026-11-26: `~/Downloads/CLIPS_2026-11-26_NEU/`.
- Darin ein Unterordner pro Clip: `NN_<streamer>_<thema>/` mit `NN_<streamer>_<thema>.mp4` und `.txt` (gleicher Name, immer beide). Nummerierung fortlaufend.
- Jeden Clip sofort liefern, sobald er fertig und geprüft ist. Enis löscht nach dem Posten.
- Bereits Gepostetes nie erneut liefern (`docs/GEPOSTET.md` pflegen).

## Inhaltsfilter (vor jeder Lieferung)
Ablehnen: Nacktheit/Sexuelles (Stripclub, Twerking, Sexszenen; in GTA 6 sehr häufig), drastische Gewalt, gefährliche Aktionen, persönliche Daten/Chat-Namen (blurren), fremdes Material (Reaktionen auf YouTube/TikTok/andere Streams), Twitch-Logos/Overlays, zu kurz oder statisch, Dinge, die schon gepostet wurden. Nichts erfinden oder irreführen.

## Posting
- Enis postet manuell, 20–23 Uhr, 2–3 starke Clips pro Abend. Kein API-Posting, keine Browser-Automation, keine gekauften Follower.

## Offen
- ~~Überschrift-Design~~: entschieden, D1 `dark` (2026-11-26).
- Lokal auf dem Mac rendern: Homebrew-`ffmpeg` hat kein libass. Vorher `export PATH=/opt/homebrew/opt/ffmpeg-full/bin:$PATH` setzen. Lokales Transkribieren geht nicht (kein faster-whisper auf dem Mac), `words.json` kommt nur aus den Workflows.
- Rohat-Clips 11, 12, 16 wurden von Enis wieder gelöscht und dürfen im neuen Stil neu geliefert werden. 16 ist in D1 neu geliefert (2026-11-26 abends). Für 11 und 12 fehlt das Rohmaterial mit `words.json` lokal.
- 2026-11-26 abends neu geliefert (D1): 16 Rohat außer Gefecht, 17 Trymacs Angelrute statt Stinger, 18 Trymacs 300 km/h im Verkehr (aus `vod-momente-2026-11-26_1804`). Nicht geliefert, weil zu schwach: Rohat „Fliegen ist meine Disziplin“ (`xrohat_2935536679_14h49m39s`, Facecam statisch, Landung nicht zu sehen). Export 14:35 komplett abgelehnt.
- PR #7: YouTube-Check, offen.
- Secrets liegen nur als GitHub-Repo-Secrets (Twitch, YouTube, TikTok). Nie ins Repo schreiben.
