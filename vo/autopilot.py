"""Lokaler Stunden-Worker. Upload nur mit explizitem YouTube-Modus."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from . import allowlist
from .clip_game import GAME_NAMES, clip_game, explicit_games
from .clip_insights import AnalysisUnavailable, MODELS, NoVisualEvidence, describe
from .common import http_json, iso, now_utc, parse_iso, read_json, secret
from .publish import (
    TT_TOKEN_URL, _tt_call, blocked_reason, tiktok_upload, youtube_access_token,
    youtube_body, youtube_is_channel, youtube_upload,
)
from .radar_clips import ClipError, prepare_clips, source_for
from .render import probe
from .texts import TIKTOK_CAPTION_MAX, YT_TITLE_MAX, build_texts
from .twitch import run_radar

INTERVAL = timedelta(hours=1)
MP4_MAX_AGE = timedelta(hours=2)
MAX_CANDIDATES = 3
TEXT_SOURCES = ("ollama", "files")
STOP_STATUSES = {"youtube_auth_failed", "youtube_unconfirmed", "youtube_wrong_channel"}
TEXT_TAG = re.compile(r"(?<!\w)[#@]\w+")
LOCAL_ENV = {"TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "YT_API_KEY",
             "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN",
             "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN", "TIKTOK_OPEN_ID"}


def load_local_env(path: Path) -> None:
    # Nur KEY=VALUE, keine Shell ausführen oder Werte protokollieren.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in LOCAL_ENV:
            raise ValueError("Lokale Zugangsdaten-Datei enthält einen unbekannten Eintrag.")
        os.environ.setdefault(key, value)


@contextmanager
def lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        if f.tell() == 0:
            f.write(b"\0")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            acquire = lambda: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            acquire()
        except OSError:
            raise RuntimeError("Auf diesem Datenordner läuft bereits ein Autopilot.") from None
        yield  # Schließen des Handles gibt die Sperre auch bei Abbruch frei.


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        try:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def prune_mp4(data: Path, *, now=None) -> int:
    """Nur vom Autopilot gerenderte Dateien entfernen, nie Quellvideos oder Metadaten."""
    data = data.absolute()
    root = data / "shorts"
    if not root.is_dir() or data.resolve() != data or root.resolve() != root:
        return 0
    cutoff = ((now or now_utc()) - MP4_MAX_AGE).timestamp()
    removed = 0
    for out in root.iterdir():
        if (not out.name.startswith(("twitch-", "youtube-")) or not out.is_dir()
                or out.resolve() != out):
            continue
        manifest_path = out / "manifest.json"
        video = out / "short.mp4"
        if (manifest_path.is_symlink() or not manifest_path.is_file()
                or video.is_symlink() or not video.is_file()):
            continue
        try:
            manifest = read_json(manifest_path, {})
            if (not isinstance(manifest, dict) or manifest.get("short_id") != out.name
                    or manifest.get("file") != video.name
                    or (manifest.get("rights") or {}).get("type") != "clipper_program"):
                continue
            if video.stat().st_mtime <= cutoff:
                video.unlink()
                removed += 1
        except (OSError, ValueError, AttributeError):
            # Eine noch gesperrte Datei beim nächsten Durchlauf erneut prüfen.
            continue
    return removed


def _video_and_proof(out: Path, sid: str, url: str, streamer: str) -> tuple[Path, dict, float]:
    manifest = read_json(out / "manifest.json", {})
    if (manifest.get("short_id") != sid or manifest.get("source") != url
            or manifest.get("streamer") != streamer or manifest.get("rights", {}).get("type") != "clipper_program"
            or manifest.get("synthetic") or manifest.get("file") != "short.mp4"):
        raise NoVisualEvidence("Radar-Herkunft oder Rechtebeleg fehlen.")
    video = out / "short.mp4"
    info = probe(video)
    if (info["width"], info["height"], info["video_codec"]) != (1080, 1920, "h264") or not 0 < info["duration"] <= 60:
        raise NoVisualEvidence("Die MP4 entspricht nicht dem Shorts-Format.")
    return video, manifest, info["duration"]


def _save_copy(out: Path, manifest: dict, cfg: dict, game: str, insights: dict, title: str) -> str:
    name = GAME_NAMES[game]
    brief = {
        "streamer": manifest["streamer"], "game": game, "scene": insights["scene"],
        "topic": name, "hook": insights["headline"],
        "title": f"{insights['headline']} | {name}",
        "description": f"{insights['observation']}\n\n{insights['question']}\n\nOriginalclip: {manifest['source']}",
        "caption": f"{insights['headline']} ({name})\n{insights['observation']}\n{insights['question']}",
    }
    texts = build_texts(brief, cfg)
    fingerprint = hashlib.sha256(insights["observation"].casefold().encode()).hexdigest()
    manifest.update(texts=texts, credit=texts["credit"],
                    autopilot={"game": game, "scene": insights["scene"], "source_title": title,
                               "observation": insights["observation"], "evidence_frames": insights["evidence_frames"],
                               "copy_sha256": fingerprint})
    atomic_json(out / "manifest.json", manifest)
    (out / "youtube.txt").write_text(f"{texts['youtube']['title']}\n\n{texts['youtube']['description']}\n", encoding="utf-8")
    (out / "tiktok.txt").write_text(texts["tiktok"]["caption"] + "\n", encoding="utf-8")
    return fingerprint


def _read_copy(out: Path, manifest: dict, cfg: dict, game: str) -> tuple[dict, str]:
    def read(name: str) -> str:
        file = out / name
        if file.is_symlink() or not file.is_file() or not 0 < file.stat().st_size <= 32 * 1024:
            raise ValueError("Clip-Textdatei fehlt oder ist ungültig.")
        return file.read_text(encoding="utf-8-sig").strip()

    title, sep, description = read("youtube.txt").partition("\n")
    title, description = title.strip(), description.strip()
    caption = read("tiktok.txt")
    if (not sep or not 0 < len(title) <= YT_TITLE_MAX or not description or not caption
            or len(description.encode("utf-8")) > 5000 or len(caption) > TIKTOK_CAPTION_MAX
            or any(c in title + description for c in "<>") or description == caption):
        raise ValueError("Clip-Texte sind leer, zu lang oder ungültig.")
    entry = allowlist.find(cfg, manifest["streamer"])
    if not entry:
        raise ValueError("Streamer-Quellenangabe fehlt.")
    yt_tags, tt_tags = TEXT_TAG.findall(description), TEXT_TAG.findall(caption)
    required = {t.casefold() if t.startswith(("#", "@")) else "#" + t.casefold()
                for t in entry.get("required_tags", [])}
    for copy, tags in ((description, yt_tags), (caption, tt_tags)):
        if (entry["name"].casefold() not in copy.casefold() or allowlist.channel_url(entry) not in copy
                or not required.issubset(t.casefold() for t in tags)):
            raise ValueError("Pflicht-Tags oder Quellenangabe fehlen.")
    common = "\n".join((title, description, caption))
    no_urls = re.sub(r"https?://\S+", "", common)
    if explicit_games(no_urls) - {game}:
        raise ValueError("Clip-Texte nennen ein anderes Spiel.")
    fingerprint = hashlib.sha256(" ".join(no_urls.casefold().split()).encode()).hexdigest()
    return {
        "hook": title, "credit": allowlist.credit_line(entry),
        "youtube": {"title": title, "description": description,
                    "tags": list(dict.fromkeys(t[1:] for t in yt_tags if t.startswith("#")))},
        "tiktok": {"caption": caption, "hashtags": list(dict.fromkeys(tt_tags))},
    }, fingerprint


def _source_ids(clip: dict) -> set[str]:
    return {clip["id"], *(clip.get("duplicates") or [])}


def _same_moment(clip: dict, prior: dict, window: float) -> bool:
    if _source_ids(clip).intersection(prior.get("source_ids", [])):
        return True
    # Auch neue Clip-IDs desselben Twitch-VOD-Ausschnitts sind Duplikate.
    now_offset, old_offset = clip.get("vod_offset"), prior.get("vod_offset")
    return bool(clip.get("video_id") and clip["video_id"] == prior.get("video_id")
                and isinstance(now_offset, (int, float)) and isinstance(old_offset, (int, float))
                and abs(now_offset - old_offset) <= window)


FINAL = {"attempted", "sent", "unconfirmed", "exported"}


def load_state(state_path: Path, known: Path | None = None) -> dict:
    """Zustand lesen und mit known_clips.json zusammenführen (Schutz vor Doppel-Uploads)."""
    state = read_json(state_path, {"last_attempt": None, "clips": {}})
    from .common import ROOT
    known = known or ROOT / "known_clips.json"
    for sid, entry in read_json(known, {"clips": {}}).get("clips", {}).items():
        merged = {**entry, **state["clips"].get(sid, {})}
        for key in ("status", "tiktok_status"):
            if entry.get(key) in FINAL and merged.get(key) not in FINAL:
                merged[key] = entry[key]
        merged["source_ids"] = sorted(set(merged.get("source_ids", [])) | set(entry.get("source_ids", [])))
        state["clips"][sid] = merged
    return state


def tiktok_local_token(data: Path, account: str, mode: str = "inbox") -> str:
    """Nur lokal erneuern: TikTok kann einen neuen Refresh-Token zurückgeben."""
    path = data / "state" / "tiktok-token.json"
    client = secret("TIKTOK_CLIENT_KEY")
    initial = secret("TIKTOK_REFRESH_TOKEN")
    fingerprint = hashlib.sha256(initial.encode()).hexdigest()
    stored = read_json(path, {})
    refresh = (stored.get("refresh_token", initial) if stored.get("client_key") == client
               and stored.get("initial_sha256") == fingerprint else initial)
    result = http_json("POST", TT_TOKEN_URL, form={
        "client_key": client, "client_secret": secret("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": refresh,
    })
    access = result["access_token"]
    replacement = result.get("refresh_token") or refresh
    if replacement != refresh:
        atomic_json(path, {"client_key": client, "initial_sha256": fingerprint, "refresh_token": replacement})
    needed = "video.publish" if mode == "direct" else "video.upload"
    if needed not in {x.strip() for x in result.get("scope", "").split(",")}:
        raise RuntimeError(f"TikTok-Berechtigung {needed} fehlt.")
    pinned_id = os.environ.get("TIKTOK_OPEN_ID", "").strip()
    if pinned_id:
        if result.get("open_id") != pinned_id:
            raise RuntimeError("TikTok-Konto stimmt nicht überein.")
    else:
        # Für alte Tokens mit bereits erteilter video.publish-Berechtigung.
        info = _tt_call("creator_info/query/", access, {})
        if info.get("creator_username", "").lstrip("@").casefold() != account.lstrip("@").casefold():
            raise RuntimeError("TikTok-Konto stimmt nicht überein.")
    return access


def _send_tiktok(video, manifest, cfg, data, state, state_path, rec, clock, token, upload):
    try:
        access = (token(data, cfg["tiktok_account"], cfg["tiktok"]["mode"])
                  if cfg["tiktok"]["mode"] == "direct" else token(data, cfg["tiktok_account"]))
    except (OSError, RuntimeError, KeyError, ValueError, SystemExit):
        return {"status": "tiktok_auth_failed"}
    rec.update(tiktok_status="attempted", tiktok_at=iso(clock()))
    state["last_attempt"] = rec["tiktok_at"]
    atomic_json(state_path, state)
    try:
        result = upload(video, manifest, cfg, access)
    except (OSError, RuntimeError, KeyError, ValueError) as exc:
        limited = "spam_risk_too_many_pending_share" in str(exc)
        rec["tiktok_status"] = "waiting" if limited else "unconfirmed"
        atomic_json(state_path, state)
        return {"status": "tiktok_inbox_limit" if limited else "tiktok_unconfirmed"}
    api_status = result.get("status")
    confirmed = {"SEND_TO_USER_INBOX": "tiktok_inbox_delivered", "PUBLISH_COMPLETE": "tiktok_published"}
    if cfg["tiktok"]["mode"] != "inbox":
        confirmed.pop("SEND_TO_USER_INBOX")
    submission = {**result, "at": iso(clock())}
    manifest["tiktok_submission"] = submission
    if api_status in confirmed:
        rec["tiktok_status"] = "sent"
        manifest.setdefault("published", {})["tiktok"] = submission
        outcome = {"status": confirmed[api_status], "api_status": api_status}
        if api_status == "PUBLISH_COMPLETE" and cfg["tiktok"]["mode"] == "direct":
            outcome["visibility"] = cfg["tiktok"]["privacy_level"]
    else:
        rec["tiktok_status"] = "unconfirmed"
        if api_status == "FAILED":
            outcome = {"status": "tiktok_failed", "api_status": api_status}
            reason = result.get("fail_reason")
            if isinstance(reason, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", reason):
                outcome["reason"] = reason
        elif api_status in {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"}:
            outcome = {"status": "tiktok_processing", "api_status": api_status}
        else:
            outcome = {"status": "tiktok_unconfirmed"}
    atomic_json(video.parent / "manifest.json", manifest)
    atomic_json(state_path, state)
    return outcome


def _send_youtube(video, manifest, cfg, mode, state, state_path, rec, clock, token, channel, upload):
    sid = manifest["short_id"]
    if blocked_reason(manifest, "youtube", {"youtube": {"approved": True}}):
        return {"status": "youtube_blocked"}
    body = youtube_body(manifest, {**cfg, "youtube": {**cfg["youtube"], "privacy_status": mode}})
    try:
        access = token()
        if not channel(access, cfg["youtube_channel"]):
            return {"status": "youtube_wrong_channel"}
    except (OSError, RuntimeError, KeyError, SystemExit):
        return {"status": "youtube_auth_failed"}
    # Reservierung vor dem Video-Upload. Ein Abbruch darf keinen Re-Upload auslösen.
    rec["status"] = "attempted"
    state["last_attempt"] = iso(clock())
    atomic_json(state_path, state)
    try:
        yt_id = upload(video, body, access)
    except (OSError, RuntimeError, KeyError, ValueError):
        rec["status"] = "unconfirmed"
        atomic_json(state_path, state)
        return {"status": "youtube_unconfirmed", "short_id": sid}
    manifest.setdefault("published", {})["youtube"] = {"video_id": yt_id, "at": iso(clock()), "visibility": mode}
    atomic_json(video.parent / "manifest.json", manifest)
    rec.update(status="sent", youtube_id=yt_id)
    atomic_json(state_path, state)
    return {"status": "youtube_sent", "short_id": sid, "youtube_id": yt_id, "visibility": mode}


def run_cycle(cfg: dict, data: Path, *, mode: str = "off", model: str = MODELS[0], tiktok_inbox: bool = False,
              text_source: str = "ollama", max_uploads: int = 1, min_gap: timedelta = INTERVAL,
              radar=run_radar, render=prepare_clips, analyze=describe,
              token=youtube_access_token, channel=youtube_is_channel, upload=youtube_upload,
              tt_token=tiktok_local_token, tt_upload=tiktok_upload, clock=now_utc) -> dict:
    if mode not in {"off", "private", "unlisted", "public"}:
        raise ValueError("Ungültiger YouTube-Modus.")
    if text_source not in TEXT_SOURCES:
        raise ValueError("Ungültige Textquelle.")
    live = mode != "off" or tiktok_inbox
    if (live and os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
            and os.environ.get("VO_ACTIONS_UPLOAD") != "1"):
        # Nur der Autopilot-Workflow schaltet Uploads auf GitHub frei.
        raise ValueError("Live-Uploads sind auf GitHub Actions nur im Autopilot-Workflow erlaubt.")
    tt = cfg["tiktok"]
    if not (tt["mode"] == "inbox" or (tt["mode"] == "direct" and tt.get("privacy_level") == "SELF_ONLY")):
        raise ValueError("Autopilot erlaubt TikTok nur als Inbox-Entwurf oder Direct Post mit SELF_ONLY.")
    state_path = data / "state" / "autopilot.json"
    state = load_state(state_path)
    old = state["clips"]
    if live and state.get("last_attempt"):
        remaining = min_gap - (clock() - parse_iso(state["last_attempt"]))
        if remaining > timedelta(0):
            return {"status": "cooldown", "wait_seconds": math.ceil(remaining.total_seconds())}
    try:
        report = radar(cfg, data / "state" / "radar_state.json", data / "radar")
    except (OSError, RuntimeError, KeyError, SystemExit):
        return {"status": "radar_failed"}

    attempts = 0
    results: list[dict] = []
    for clip in report["top"]:
        try:
            sid, url, streamer = source_for(clip, cfg)
        except ClipError:
            continue
        game = clip_game(clip, report.get("gta_categories", {}))
        if game not in cfg.get("gta_filter", {}).get("games", GAME_NAMES):
            game = None
        title = clip.get("title", "").casefold()
        if any(w.casefold() in title for w in cfg.get("gta_filter", {}).get("title_blocklist", [])):
            continue  # z. B. Nacktszenen: Risiko für Kanal-Verwarnungen
        previous = old.get(sid, {})
        final_states = {"attempted", "sent", "unconfirmed"}
        wants_youtube = mode != "off" and previous.get("status") not in final_states
        wants_tiktok = tiktok_inbox and previous.get("tiktok_status") not in final_states | {"exported"}
        if (not game or (live and not (wants_youtube or wants_tiktok))
                or (not live and previous)):
            continue
        others = [v for k, v in old.items() if k != sid]
        if any(_same_moment(clip, v, cfg["radar"]["dedupe_window_seconds"]) for v in others):
            continue
        if attempts >= MAX_CANDIDATES * max_uploads:
            break
        out = data / "shorts" / sid
        if out.exists() and not (out / "short.mp4").is_file():
            continue  # Altdatei bereinigt. Metadaten bleiben als Duplikatsperre.
        attempts += 1
        if not out.exists():
            result = render({"top": [clip], "gta_categories": report.get("gta_categories", {})},
                            cfg, data, limit=1, handoff=False)
            if sid not in result["rendered"]:
                continue
        try:
            video, manifest, duration = _video_and_proof(out, sid, url, streamer)
            already = manifest.get("published", {})
            wants_youtube = wants_youtube and not already.get("youtube")
            wants_tiktok = wants_tiktok and not already.get("tiktok")
            if live and not (wants_youtube or wants_tiktok):
                continue
            if text_source == "files":
                texts, copy_sha = _read_copy(out, manifest, cfg, game)
            else:
                insights = analyze(video, duration, game, model)
                copy_sha = hashlib.sha256(insights["observation"].casefold().encode()).hexdigest()
        except AnalysisUnavailable:
            return {"status": "analysis_unavailable"}
        except (NoVisualEvidence, OSError, RuntimeError, ValueError, StopIteration):
            continue

        if any(v.get("copy_sha256") == copy_sha for v in others):
            continue
        if text_source == "files":
            manifest.update(texts=texts, credit=texts["credit"],
                            autopilot={"game": game, "text_source": "files", "copy_sha256": copy_sha})
            atomic_json(out / "manifest.json", manifest)
        else:
            _save_copy(out, manifest, cfg, game, insights, clip.get("title", ""))
        rec = {"status": "prepared", **previous, "copy_sha256": copy_sha,
               "source_ids": sorted(_source_ids(clip)), "video_id": clip.get("video_id"),
               "vod_offset": clip.get("vod_offset")}
        old[sid] = rec
        atomic_json(state_path, state)
        if not live:
            return {"status": "prepared", "short_id": sid}
        yt = (_send_youtube(video, manifest, cfg, mode, state, state_path, rec, clock, token, channel, upload)
              if wants_youtube else {"status": "off_or_already_attempted"})
        if not tiktok_inbox:
            result = yt
        else:
            tt = (_send_tiktok(video, manifest, cfg, data, state, state_path, rec, clock, tt_token, tt_upload)
                  if wants_tiktok else {"status": "off_or_already_attempted"})
            result = {"status": "api_finished", "short_id": sid, "youtube": yt, "tiktok": tt}
        results.append(result)
        # Anmeldefehler oder unklarer Upload: in diesem Durchgang nichts weiter senden.
        if (len(results) >= max_uploads or yt.get("status") in STOP_STATUSES):
            break
    if len(results) == 1:
        return results[0]
    if results:
        return {"status": "batch", "results": results,
                "youtube_sent": sum(r.get("status") == "youtube_sent" or
                                    (r.get("youtube") or {}).get("status") == "youtube_sent" for r in results)}
    return {"status": "no_suitable_clip", "examined": attempts}


def run(cfg: dict, data: Path, *, mode: str, model: str, watch: bool,
        tiktok_inbox: bool = False, text_source: str = "ollama", max_uploads: int = 1,
        min_gap_minutes: int = 60) -> int:
    root = data.resolve() / "autopilot"
    print(f"Autopilot · YouTube-Kanal {cfg['youtube_channel']} · Sichtbarkeit: {mode} · "
          f"höchstens {max_uploads} Short(s) pro Durchgang · MP4-Aufbewahrung: 2 Stunden · TikTok-Inbox: {tiktok_inbox}.",
          flush=True)
    try:
        with lock(root / "state" / "run.lock"):
            while True:
                started = time.monotonic()
                removed = prune_mp4(root)
                result = {**run_cycle(cfg, root, mode=mode, model=model, tiktok_inbox=tiktok_inbox,
                                      text_source=text_source, max_uploads=max_uploads,
                                      min_gap=timedelta(minutes=min_gap_minutes)), "mp4_removed": removed}
                atomic_json(root / "state" / "last-run.json", {**result, "at": iso(now_utc())})
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if not watch:
                    statuses = {result["status"], *(r.get("status") for r in result.get("results", []))}
                    return 1 if statuses & ({"radar_failed", "analysis_unavailable"} | STOP_STATUSES) else 0
                next_check = max(1, INTERVAL.total_seconds() - (time.monotonic() - started))
                time.sleep(result.get("wait_seconds", next_check))
    except KeyboardInterrupt:
        return 0
