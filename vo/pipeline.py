"""Baut aus einem Brief das Short-Paket für Schnitt und Freigabe."""
from __future__ import annotations

from pathlib import Path

from .common import iso, now_utc, write_json
from .render import render_short
from .texts import build_texts


def make_short(brief: dict, cfg: dict, shorts_root: Path, base_dir: Path, short_id: str,
               *, source_url: str | None = None, require_subtitles: bool = True) -> Path:
    texts = build_texts(brief, cfg)
    out = shorts_root / short_id
    result = render_short(brief, texts["hook"], out, cfg, base_dir,
                          require_subtitles=require_subtitles)
    manifest = {"short_id": short_id, "created_at": iso(now_utc()),
                "synthetic": result["rights"]["type"] == "synthetic",
                "source": source_url or brief["source"], "rights": result["rights"], "file": result["file"],
                "video": result["video"], "texts": texts, "credit": texts.get("credit", ""),
                "streamer": brief.get("streamer"), "published": {}}
    if brief.get("public_video_url"):
        manifest["public_video_url"] = brief["public_video_url"]
    write_json(out / "manifest.json", manifest)
    (out / "youtube.txt").write_text(f"{texts['youtube']['title']}\n\n{texts['youtube']['description']}\n", encoding="utf-8")
    (out / "tiktok.txt").write_text(texts["tiktok"]["caption"] + "\n", encoding="utf-8")
    return out
