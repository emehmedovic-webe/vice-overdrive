"""Radar-Treffer herunterladen, schneiden und der Freigabe übergeben. Kein Upload."""
from __future__ import annotations

import math
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import allowlist
from .clip_game import clip_game
from .common import media_env, write_json
from .pipeline import make_short
from .publish import TT_MAX_SINGLE_CHUNK, make_batch, publish
from .render import probe

DEFAULT_LIMIT = 3
MAX_LIMIT = 5
# H.264/AAC und MP4-Zeitstempel können minimal über die Schnittzeit hinausgehen.
MAX_CUT_SECONDS = 59
DOWNLOAD_TIMEOUT = 120
SOURCE_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}


class ClipError(RuntimeError):
    """Fehler mit bewusst knapper, loggeeigneter Meldung."""


def source_for(clip: dict, cfg: dict) -> tuple[str, str, str]:
    """Nur kanonische öffentliche URLs, nur aus den geprüften Radar-Treffern."""
    streamer = clip.get("streamer_login")
    entry = allowlist.find(cfg, streamer) if isinstance(streamer, str) else None
    if not entry or not entry.get("active", True) or not allowlist.has_proof(entry):
        raise ClipError("Kein aktiver Allowlist-Eintrag mit Beleg.")

    platform = clip.get("platform")
    source_id = clip.get("id") or ""
    if not isinstance(source_id, str):
        raise ClipError("Ungültige Radar-ID.")
    raw_url = clip.get("url")
    if not isinstance(raw_url, str):
        raise ClipError("Ungültige Video-URL.")
    try:
        url = urlsplit(raw_url)
    except ValueError:
        raise ClipError("Ungültige Video-URL.") from None
    if url.scheme != "https":
        raise ClipError("Ungültige Video-URL.")
    login = entry["twitch_login"].lower()
    if platform == "twitch" and re.fullmatch(r"[A-Za-z0-9_-]{1,180}", source_id):
        if not (
            (url.netloc == "clips.twitch.tv" and url.path == f"/{source_id}")
            or (url.netloc in {"twitch.tv", "www.twitch.tv"}
                and url.path == f"/{login}/clip/{source_id}")
        ):
            raise ClipError("Twitch-URL passt nicht zur Radar-ID bzw. zum Kanal.")
        return f"twitch-{source_id}", f"https://clips.twitch.tv/{source_id}", login

    if platform == "youtube" and re.fullmatch(r"yt:[A-Za-z0-9_-]{11}", source_id):
        video_id = source_id[3:]
        if not (
            (url.netloc in {"youtube.com", "www.youtube.com"} and (
                (url.path == "/watch" and parse_qs(url.query).get("v") == [video_id])
                or url.path == f"/shorts/{video_id}"
            )) or (url.netloc == "youtu.be" and url.path == f"/{video_id}")
        ):
            raise ClipError("YouTube-URL passt nicht zur Radar-ID.")
        if not entry.get("youtube_handle") or not allowlist.has_proof(entry, "youtube_download_proof"):
            raise ClipError("YouTube bleibt Radar-Treffer: Plattform-Downloadfreigabe fehlt.")
        return f"youtube-{video_id}", f"https://www.youtube.com/watch?v={video_id}", login
    raise ClipError("Unbekannte Plattform oder ungültige Radar-ID.")


def download_clip(url: str, platform: str, dest: Path, cut_seconds: float) -> Path:
    # Keine GitHub-/API-Secrets, Nutzer-Konfig, Plugins oder Cookies an yt-dlp übergeben.
    env = media_env()
    cmd = [
        "yt-dlp", "--ignore-config", "--no-plugin-dirs", "--no-cache-dir", "--no-playlist",
        "--socket-timeout", "15", "--retries", "1", "--fragment-retries", "1",
        "--no-progress", "--output", "source.%(ext)s",
    ]
    if platform == "youtube":
        cmd += ["--js-runtimes", "node", "--download-sections", f"*0-{cut_seconds:g}",
                "--format", "bv*[height<=1080]+ba/b[height<=1080]"]
    else:
        cmd += ["--max-filesize", "128M", "--format", "b[height<=1080]/b"]
    try:
        subprocess.run([*cmd, "--", url], cwd=dest, env=env, check=True,
                       timeout=DOWNLOAD_TIMEOUT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise ClipError("yt-dlp fehlt.") from None
    except subprocess.TimeoutExpired:
        raise ClipError("Download-Zeitlimit erreicht.") from None
    except subprocess.CalledProcessError:
        raise ClipError("Download fehlgeschlagen (Quelle oder Runner-Zugriff nicht verfügbar).") from None
    files = [p for p in dest.glob("source.*") if p.suffix in SOURCE_EXTENSIONS and p.is_file()]
    if len(files) != 1 or not 0 < files[0].stat().st_size <= 128 * 1024 * 1024:
        raise ClipError("Kein eindeutiges Quellvideo innerhalb des Größenlimits.")
    return files[0]


def prepare_clips(report: dict, cfg: dict, data: Path, *, limit: int = DEFAULT_LIMIT,
                  download=download_clip, handoff: bool = True) -> dict:
    """Verarbeitet höchstens limit geeignete Treffer in Radar-Reihenfolge."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit muss zwischen 1 und {MAX_LIMIT} liegen.")
    if cfg["tiktok"]["mode"] not in {"inbox", "direct"}:
        raise ValueError("Unbekannter TikTok-Modus.")
    seconds = min(float(cfg["render"]["max_seconds"]), MAX_CUT_SECONDS)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("render.max_seconds muss eine positive, endliche Zahl sein.")
    cfg = {**cfg, "render": {**cfg["render"], "width": 1080, "height": 1920,
                             "max_seconds": seconds, "max_video_bitrate": "7M"}}
    data = data.resolve()
    shorts_root = data / "shorts"
    shorts_root.mkdir(parents=True, exist_ok=True)
    result = {"rendered": [], "skipped": [], "failed": []}
    attempts = 0
    seen = set()
    for position, clip in enumerate(report["top"], start=1):
        try:
            short_id, url, streamer = source_for(clip, cfg)
        except ClipError as exc:
            result["skipped"].append({"rank": position, "reason": str(exc)})
            continue
        final = shorts_root / short_id
        if short_id in seen or final.exists():
            result["skipped"].append({"short_id": short_id, "reason": "Doppelter oder bereits geschnittener Treffer."})
            continue
        if attempts >= limit:
            break
        attempts += 1
        seen.add(short_id)
        try:
            with tempfile.TemporaryDirectory(prefix=".radar-clip-", dir=shorts_root) as temp:
                stage = Path(temp)
                src = download(url, clip["platform"], stage, seconds)
                info = probe(src)
                duration = min(info["duration"], seconds)
                if not math.isfinite(duration) or duration <= 0:
                    raise ClipError("Quelldatei hat keine gültige Dauer.")
                topic = " ".join(str(clip.get("title") or "").split())
                topic = topic.replace("<", "").replace(">", "")[:85].strip()
                topic = topic or "GTA-Clip"
                brief = {
                    "source": src.name, "start": 0, "duration": duration,
                    "streamer": streamer, "rights": {"type": "clipper_program"},
                    "topic": topic, "title": topic, "hook": topic,
                    "description": f"{topic}\nOriginalclip: {url}",
                }
                # Bei bestätigtem Spiel auch ohne Bildmodell keine falschen GTA-Hashtags.
                game = clip_game(clip, report.get("gta_categories", {}))
                if game:
                    brief["game"] = game
                out = make_short(brief, cfg, stage, stage, short_id, source_url=url, require_subtitles=False)
                video = out / "short.mp4"
                if not 0 < probe(video)["duration"] <= 60:
                    raise ClipError("Ausgabedauer liegt außerhalb des Shorts-Limits.")
                if video.stat().st_size > TT_MAX_SINGLE_CHUNK:
                    raise ClipError("Short überschreitet das Einzel-Upload-Limit der TikTok-Inbox.")
                out.rename(final)
        except ClipError as exc:
            result["failed"].append({"short_id": short_id, "reason": str(exc)})
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, StopIteration):
            result["failed"].append({"short_id": short_id, "reason": "Quelldatei konnte nicht geprüft oder geschnitten werden."})
        else:
            result["rendered"].append(short_id)

    if handoff and result["rendered"]:
        make_batch(shorts_root, data / "approvals")
        for target in ("tiktok", "youtube"):
            publish(target, shorts_root, data / "approvals", data / "logs", cfg, live=False)
    write_json(data / "radar" / "radar-clips-result.json", result)
    return result
