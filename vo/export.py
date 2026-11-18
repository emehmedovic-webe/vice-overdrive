"""TikTok-Export: übrige GTA-Clips fertig schneiden, damit Enis sie selbst postet.

Ein exportierter Clip wird im Autopilot-Zustand als tiktok_status="exported" markiert
und danach nie mehr an die TikTok-Inbox geschickt. YouTube-Uploads bleiben unberührt.
Clips, die schon als Entwurf geschickt wurden ("sent"/"attempted"), kommen nicht in den Export.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .autopilot import _same_moment, _source_ids, atomic_json, load_state, lock
from .clip_game import GAME_NAMES, clip_game
from .common import iso, now_utc, read_json
from .radar_clips import ClipError, prepare_clips, source_for
from .texts import tiktok_export_caption
from .twitch import run_radar

SKIP_TIKTOK = {"attempted", "sent", "exported"}


def export_caption(src: Path) -> str:
    """Caption für den Export: nur Beschreibung + Hashtags, ohne Link, Credit oder Standardfrage.

    Quelle und Rechte bleiben im Manifest, im Autopilot-Zustand und in CAPTIONS.md (intern).
    """
    manifest = read_json(src / "manifest.json", {})
    tiktok = manifest.get("texts", {}).get("tiktok", {})
    description = (manifest.get("autopilot", {}).get("observation") or manifest.get("tiktok_description") or "").strip()
    hashtags = tiktok.get("hashtags") or []
    if not description:
        raw = (src / "tiktok.txt").read_text(encoding="utf-8") if (src / "tiktok.txt").is_file() else ""
        hashtags = hashtags or re.findall(r"(?<!\w)#\w+", raw)
        description = re.sub(r"(?<!\w)#\w+", "", raw)
    return tiktok_export_caption(description, hashtags)


def run_export(cfg: dict, root: Path, out: Path, *, limit: int = 15,
               radar=run_radar, render=prepare_clips, clock=now_utc) -> list[dict]:
    root = root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = root.parent / "export-work"
    state_path = root / "state" / "autopilot.json"
    gfilter = cfg.get("gta_filter", {})
    allowed = gfilter.get("games", GAME_NAMES)
    blocked = [w.casefold() for w in gfilter.get("title_blocklist", [])]
    exported: list[dict] = []
    with lock(root / "state" / "run.lock"):
        state = load_state(state_path)
        old = state["clips"]
        report = radar(cfg, root / "state" / "radar_state.json", root / "radar")
        for clip in report["top"]:
            if len(exported) >= limit:
                break
            try:
                sid, _url, streamer = source_for(clip, cfg)
            except ClipError:
                continue
            game = clip_game(clip, report.get("gta_categories", {}))
            title = clip.get("title", "")
            if game not in allowed or any(w in title.casefold() for w in blocked):
                continue
            previous = old.get(sid, {})
            if previous.get("tiktok_status") in SKIP_TIKTOK:
                continue
            done = [v for k, v in old.items() if k != sid and v.get("tiktok_status") in SKIP_TIKTOK]
            if any(_same_moment(clip, v, cfg["radar"]["dedupe_window_seconds"]) for v in done):
                continue
            try:
                result = render({"top": [clip], "gta_categories": report.get("gta_categories", {})},
                                cfg, work, limit=1, handoff=False)
            except (OSError, RuntimeError, ValueError, ClipError):
                continue
            src = work / "shorts" / sid
            if sid not in result.get("rendered", []) or not (src / "short.mp4").is_file():
                continue
            check = previous.get("tiktok_status") == "unconfirmed"
            slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:40] or "clip"
            name = f"{len(exported) + 1:02d}_{streamer}_{slug}" + ("_PRUEFEN-evtl-schon-in-Inbox" if check else "")
            folder = out / name
            try:
                caption = export_caption(src)
            except ValueError:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / "short.mp4", folder / "video.mp4")
            (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
            rec = {"status": "prepared", **previous, "source_ids": sorted(_source_ids(clip)),
                   "video_id": clip.get("video_id"), "vod_offset": clip.get("vod_offset"),
                   "tiktok_status": "exported", "tiktok_at": iso(clock())}
            old[sid] = rec
            atomic_json(state_path, state)
            exported.append({"file": name, "streamer": streamer, "title": title,
                             "source": clip.get("url", ""), "caption": caption, "check": check})
    notes = ["# TikTok-Export (selbst posten)", "",
             "Diese Clips gehen NICHT mehr automatisch an TikTok. Bereits gesendete Entwürfe sind nicht dabei.",
             "Nur caption.txt wird gepostet. Die Quelle hier ist eine interne Notiz und gehört nicht in die Caption.", ""]
    for e in exported:
        notes += [f"## {e['file']}" + (" ⚠️ evtl. schon in der TikTok-Inbox, erst prüfen" if e["check"] else ""),
                  f"Quelle: {e['source']}", "", "```", e["caption"], "```", ""]
    (out / "CAPTIONS.md").write_text("\n".join(notes), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return exported
