"""Feinschnitt im Format v3 aus einem Export-Ordner.

Erwartet <ordner>/_roh/source.mp4, <ordner>/_roh/words.json und <ordner>/edit.json:
{
  "streamer": "montanablack88",
  "start": 3.0, "end": 24.5,                  # Ausschnitt im Rohschnitt (12–30 s empfohlen)
  "headline": "Monte schaltet den Wachmann mit dem Elektroschocker aus ⚡",
  "bubbles": [{"start": 0.2, "end": 2.5, "text": "Erst ganz freundlich quatschen …"}],
  "punch": [{"start": 7.4, "end": 10.0, "text": "Gespräch beendet."}],
  "caption": "Monte quatscht den Wachmann freundlich an und greift dann zum Elektroschocker.",
  "tags": ["#gta6", "#montanablack", "#elektroschocker"],
  "facecam": {...}, "game_x": 203,           # optional, sonst aus config.json
  "layout": "split" | "pip",                 # pip = Gameplay ganz, Facecam als Kasten oben
  "blur": [{"x": 700, "y": 950, "w": 540, "h": 100}]   # optional: eingebrannte Fremd-Untertitel verwischen
}
Zeiten von bubbles/punch relativ zum Ausschnittsanfang. Schreibt video.mp4 + caption.txt.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import allowlist
from .split_render import load_words, render_split
from .texts import tiktok_caption_problems


def compose(folder: Path, cfg: dict) -> Path:
    folder = Path(folder)
    edit = json.loads((folder / "edit.json").read_text(encoding="utf-8"))
    entry = allowlist.find(cfg, edit["streamer"])
    if not entry:
        raise SystemExit(f"Streamer nicht in der Allowlist: {edit['streamer']}")
    facecam = edit.get("facecam") or entry.get("facecam")
    if not facecam:
        raise SystemExit("Keine Facecam-Box (edit.json oder config.json) – Format v3 nicht möglich.")
    start, end = float(edit.get("start", 0)), float(edit["end"])
    if not 0 < end - start <= 60:
        raise SystemExit("Ausschnitt muss zwischen 0 und 60 Sekunden lang sein.")
    caption = f"{edit['caption'].strip()}\n\n{' '.join([allowlist.tiktok_handle(entry), *edit['tags']])}"
    problems = tiktok_caption_problems(caption)
    if problems:
        raise SystemExit("Caption: " + " ".join(problems))
    r = cfg["render"]
    out = render_split(folder / "_roh" / "source.mp4", folder / "video.mp4", start=start, duration=end - start,
                       facecam=facecam, game_x=edit.get("game_x", entry.get("game_x")), blur=edit.get("blur", []),
                       headline=edit["headline"], words=load_words(folder / "_roh" / "words.json"),
                       bubbles=edit.get("bubbles", []), punch=edit.get("punch", []),
                       outro_seconds=float(r.get("outro_seconds", 2.5)),
                       font=r.get("headline_font", "Inter Display"), max_bitrate="3M",
                       layout=edit.get("layout", "split"), hook=edit.get("hook"))
    (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
    return out
