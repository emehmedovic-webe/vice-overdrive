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

## Format (Hook-Stil, von Enis am 2026-11-26 freigegeben)
- Facecam oben (1080x750, Streamer immer komplett sichtbar), Gameplay unten.
- Weiße Überschrift-Box auf der Naht: ein Satz mit Streamer-Name und ⁉️😳.
- Der Clip startet direkt am bzw. kurz vor dem Höhepunkt.
- `hook` in edit.json: großer gelber Text in den ersten 2,6 s, neugierig machend und wahr (z. B. „Rohat hat keine Ahnung, was gleich passiert 😳“).
- 1 eigene Text-Einblendung (`bubbles`), nur wenn sie stimmt. Emojis wie 💀 rendern nicht; 😳 😂 🔥 funktionieren.
- Wort-für-Wort-Untertitel des exakten Wortlauts (unklare Whisper-Wörter in `_roh/words.json` entfernen, nichts erfinden).
- Originalton, keine Bewegungseffekte, kein Wasserzeichen, Supercar-Outro (`assets/outro`).
- Länge 12–30 s (höchstens 60 s).
- Ein Sprachkommentar ist nicht gewünscht.

Beispiel `edit.json`:
```json
{"streamer": "xrohat", "start": 14.0, "end": 45.0,
 "headline": "Rohat rammt einen SUV – der hebt fast ab ⁉️😳",
 "hook": {"text": "Rohat hat keine Ahnung, was gleich passiert 😳", "seconds": 2.6},
 "bubbles": [{"start": 12.0, "end": 18.5, "text": "Der Verkehr in GTA 6 kennt keine Gnade 😂"}],
 "caption": "Rohat rammt in GTA 6 einen SUV, der fast umkippt, und regt sich danach über den Verkehr auf.",
 "tags": ["#gta6", "#xrohat", "#verkehr"]}
```
Optional: `facecam` {x,y,w,h} und `game_x` (im 1920x1080-Bild), wenn das Layout vom Standard in `config.json` abweicht (z. B. FC-Streams), sowie `blur` für Chat-Namen.

## Caption (.txt)
- Zeile 1: ein wahrer Satz. Zeile 2: leer. Zeile 3: Hashtags.
- Hashtags: `#gta6` (bzw. Spiel-Tag) `#<streamer>` `#<thema>` `#fyp #foryou #foryoupage #fy`.
- **Kein @-Erwähnen des Streamers.**
- Reines ASCII, UTF-8 ohne BOM. Hinweis: TikTok macht eingefügte Hashtags nicht fett. Entweder selbst tippen oder nach dem Einfügen hinter jedem Hashtag ein Leerzeichen setzen.
- Keine URLs, keine Quellenangaben, keine Fragen.

## Lieferung
- Ein Ordner pro Tag: `~/Downloads/CLIPS_<JJJJ-MM-TT>/`.
- Darin ein Unterordner pro Clip: `NN_<streamer>_<thema>/` mit `NN_<streamer>_<thema>.mp4` und `.txt` (gleicher Name, immer beide). Nummerierung fortlaufend.
- Jeden Clip sofort liefern, sobald er fertig und geprüft ist. Enis löscht nach dem Posten.
- Bereits Gepostetes nie erneut liefern (`docs/GEPOSTET.md` pflegen).

## Inhaltsfilter (vor jeder Lieferung)
Ablehnen: Nacktheit/Sexuelles (Stripclub, Twerking, Sexszenen; in GTA 6 sehr häufig), drastische Gewalt, gefährliche Aktionen, persönliche Daten/Chat-Namen (blurren), fremdes Material (Reaktionen auf YouTube/TikTok/andere Streams), Twitch-Logos/Overlays, zu kurz oder statisch, Dinge, die schon gepostet wurden. Nichts erfinden oder irreführen.

## Posting
- Enis postet manuell, 20–23 Uhr, 2–3 starke Clips pro Abend. Kein API-Posting, keine Browser-Automation, keine gekauften Follower.

## Offen
- PR #42: Allowlist Sidney + Willy, Monte aus, GTA V/365 Tage, VOD-Fallback auf Nicht-GTA-Streams, Export `--any-game`/`--logins`, Hook-Stil, Captions ohne @, diese Übergabe. Noch nicht gemergt.
- PR #7: YouTube-Check, offen.
- Secrets liegen nur als GitHub-Repo-Secrets (Twitch, YouTube, TikTok). Nie ins Repo schreiben.
