"""TikTok-Export: übrige GTA-Clips fertig schneiden, damit Enis sie selbst postet.

Ein exportierter Clip wird im Autopilot-Zustand als tiktok_status="exported" markiert
und danach nie mehr an die TikTok-Inbox geschickt. YouTube-Uploads bleiben unberührt.
Clips, die schon als Entwurf geschickt wurden ("sent"/"attempted"), kommen nicht in den Export.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import allowlist
from .autopilot import _same_moment, _source_ids, atomic_json, load_state, lock
from .clip_game import GAME_NAMES, clip_game
from .common import iso, now_utc, read_json
from .radar_clips import ClipError, prepare_clips, source_for
from .texts import tiktok_export_caption
from .twitch import run_radar

SKIP_TIKTOK = {"attempted", "pending", "sent", "exported"}
# Enis 2026-11-18: Mischung pro Paket, z. B. 1–2 Monte, 1–2 Rohat, 1–2 Trymacs, nicht nur einer.
MAX_PER_STREAMER = 2


def mix_by_streamer(top: list[dict]) -> list[dict]:
    """Abwechselnd nach Streamer sortieren, innerhalb eines Streamers die meistgesehenen Clips zuerst."""
    groups: dict[str, list[dict]] = {}
    for clip in top:
        groups.setdefault(str(clip.get("streamer_login") or "").casefold(), []).append(clip)
    # Viral-Potenzial zuerst (Enis 2026-11-23): meiste Aufrufe, bei Gleichstand schnellster Zuwachs.
    queues = [sorted(g, key=lambda c: (-(c.get("view_count") or 0), -(c.get("velocity_per_hour") or 0)))
              for g in groups.values()]
    queues.sort(key=lambda q: -(q[0].get("view_count") or 0) if q else 0)
    mixed: list[dict] = []
    while any(queues):
        for q in queues:
            if q:
                mixed.append(q.pop(0))
    return mixed


def export_caption(src: Path, cfg: dict | None = None, streamer: str | None = None) -> str:
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
    entry = allowlist.find(cfg, manifest.get("streamer") or streamer) if cfg else None
    return tiktok_export_caption(description, hashtags, allowlist.tiktok_handle(entry) if entry else "")


def run_export(cfg: dict, root: Path, out: Path, *, limit: int = 15, per_streamer: int = MAX_PER_STREAMER,
               radar=run_radar, render=prepare_clips, clock=now_utc, redo: frozenset[str] = frozenset(),
               any_game: bool = False) -> list[dict]:
    """redo = Clip-Slugs, die gezielt neu geschnitten werden (z. B. für ein neues Format), auch wenn
    sie schon exportiert wurden. Ist redo gesetzt, werden nur diese Clips exportiert."""
    root = root.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = root.parent / "export-work"
    state_path = root / "state" / "autopilot.json"
    gfilter = cfg.get("gta_filter", {})
    allowed = gfilter.get("games", GAME_NAMES)
    blocked = [w.casefold() for w in gfilter.get("title_blocklist", [])]
    exported: list[dict] = []
    # Zurückgehaltene Clips mit Klartext-Grund, damit nichts still verschwindet.
    held: list[dict] = []
    locked_streamers: dict[str, str] = {}
    with lock(root / "state" / "run.lock"):
        state = load_state(state_path)
        old = state["clips"]
        report = radar(cfg, root / "state" / "radar_state.json", root / "radar")
        counts: dict[str, int] = {}
        for clip in mix_by_streamer(report["top"]):
            if len(exported) >= limit:
                break
            login = str(clip.get("streamer_login") or "").casefold()
            if counts.get(login, 0) >= per_streamer:
                continue
            title = clip.get("title", "")
            wanted = bool(redo) and any(r and r in str(clip.get("url", "")) for r in redo)
            if redo and not wanted:
                continue
            try:
                sid, _url, streamer = source_for(clip, cfg)
            except ClipError as exc:
                entry = allowlist.find(cfg, login) if login else None
                reason = allowlist.proof_problem(entry) or str(exc)
                if entry and reason != str(exc):
                    locked_streamers.setdefault(entry.get("name") or login, reason)
                else:
                    held.append({"streamer": login, "title": title, "source": clip.get("url", ""), "reason": reason})
                continue
            game = clip_game(clip, report.get("gta_categories", {}))
            if game not in allowed and not any_game:
                continue
            hit = next((w for w in blocked if w in title.casefold()), None)
            if hit:
                held.append({"streamer": streamer, "title": title, "source": clip.get("url", ""),
                             "reason": f"Titel enthält Risiko-Wort „{hit}“ (title_blocklist)"})
                continue
            previous = old.get(sid, {})
            if previous.get("tiktok_status") in SKIP_TIKTOK and not wanted:
                continue
            done = [v for k, v in old.items() if k != sid and v.get("tiktok_status") in SKIP_TIKTOK]
            if not wanted and any(_same_moment(clip, v, cfg["radar"]["dedupe_window_seconds"]) for v in done):
                continue
            try:
                result = render({"top": [clip], "gta_categories": report.get("gta_categories", {})},
                                cfg, work, limit=1, handoff=False)
            except (OSError, RuntimeError, ValueError, ClipError) as exc:
                held.append({"streamer": streamer, "title": title, "source": clip.get("url", ""),
                             "reason": f"Schnitt fehlgeschlagen: {exc}"})
                continue
            src = work / "shorts" / sid
            if sid not in result.get("rendered", []) or not (src / "short.mp4").is_file():
                why = next((f.get("reason") for f in result.get("failed", []) if f.get("short_id") == sid),
                           "kein Video erzeugt")
                held.append({"streamer": streamer, "title": title, "source": clip.get("url", ""),
                             "reason": f"Schnitt fehlgeschlagen: {why}"})
                continue
            check = previous.get("tiktok_status") == "unconfirmed"
            slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:40] or "clip"
            name = f"{len(exported) + 1:02d}_{streamer}_{slug}" + ("_PRUEFEN-evtl-schon-in-Inbox" if check else "")
            folder = out / name
            try:
                caption = export_caption(src, cfg, streamer)
            except ValueError as exc:
                held.append({"streamer": streamer, "title": title, "source": clip.get("url", ""),
                             "reason": f"Caption-Prüfung: {exc}"})
                continue
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / "short.mp4", folder / "video.mp4")
            # Format v3: Rohschnitt + Wortliste zum Nachbearbeiten (eigene Überschrift/Kommentare). Nie posten.
            for raw, name_ in (("rohschnitt.mp4", "source.mp4"), ("words.json", "words.json")):
                if (src / raw).is_file():
                    (folder / "_roh").mkdir(exist_ok=True)
                    shutil.copyfile(src / raw, folder / "_roh" / name_)
            (folder / "caption.txt").write_text(caption + "\n", encoding="utf-8")
            review = """VICE OVERDRIVE — MANUELLE FREIGABE VOR DEM POSTEN

STATUS: NICHT GEPRÜFT / NICHT POSTEN

Video vollständig ansehen (nicht nur Stichproben):
[ ] Streamer/Facecam ist klar und erkennbar sichtbar; Gesicht nicht abgeschnitten oder verdeckt.
[ ] Bildausschnitt zeigt den relevanten Gameplay-Moment; keine wichtigen Inhalte abgeschnitten.
[ ] Anfang, Ende, Übergänge, Hook, Wasserzeichen und alle Overlays geprüft.
[ ] Untertitel stimmen vollständig mit dem gesprochenen Inhalt überein; keine erfundenen Wörter.
[ ] Ton/Musik/Sounds geprüft; Nutzungsrechte für Audio geklärt.
[ ] Chat, Namen und eingeblendete Inhalte auf Privates, Beleidigungen und Regelverstöße geprüft.
[ ] Kein erkennbar problematischer Inhalt (z. B. Hass, Drohungen, Belästigung, Sexualisierung,
    gefährliche Handlungen oder grafische/glorifizierte Gewalt).
[ ] Quelle, Streamer-Zuordnung und konkrete Nutzungs-/Clipper-Freigabe anhand eines Belegs geprüft.
[ ] Caption beschreibt exakt diesen Clip; Hashtags sind relevant und nicht irreführend.
[ ] Keine künstliche Interaktion, gekauften Views/Follower oder Engagement-Bait.

Erst nach ALLEN Häkchen manuell freigeben und selbst in TikTok hochladen.
Wenn etwas unklar ist: NICHT posten. Ein sichtbarer Streamer oder ein Export allein beweist
keine Nutzungsrechte und garantiert keine TikTok-Empfehlung.
"""
            (folder / "REVIEW_REQUIRED.txt").write_text(review, encoding="utf-8")
            rec = {"status": "prepared", **previous, "source_ids": sorted(_source_ids(clip)),
                   "video_id": clip.get("video_id"), "vod_offset": clip.get("vod_offset"),
                   "tiktok_status": "exported", "tiktok_at": iso(clock())}
            old[sid] = rec
            atomic_json(state_path, state)
            counts[login] = counts.get(login, 0) + 1
            exported.append({"file": name, "streamer": streamer, "title": title,
                             "source": clip.get("url", ""), "caption": caption, "check": check})
    notes = ["# TikTok-Export (selbst posten)", "",
             "Diese Clips gehen NICHT mehr automatisch an TikTok. Bereits gesendete Entwürfe sind nicht dabei.",
             "Nur caption.txt wird gepostet. Die Quelle hier ist eine interne Notiz und gehört nicht in die Caption.", ""]
    for e in exported:
        notes += [f"## {e['file']}" + (" ⚠️ evtl. schon in der TikTok-Inbox, erst prüfen" if e["check"] else ""),
                  f"Quelle: {e['source']}", "", "```", e["caption"], "```", ""]
    if locked_streamers or held:
        notes += ["# Zurückgehalten (NICHT exportiert)", "",
                  "Diese Clips/Streamer hat die Prüfung gestoppt. Nichts davon posten, bis der Grund behoben ist.", ""]
        for name, reason in sorted(locked_streamers.items()):
            notes.append(f"- **{name}** gesperrt: {reason}")
        for h in held:
            notes.append(f"- {h['streamer']} – „{h['title']}“: {h['reason']} (intern: {h['source']})")
        notes.append("")
    (out / "CAPTIONS.md").write_text("\n".join(notes), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return exported
