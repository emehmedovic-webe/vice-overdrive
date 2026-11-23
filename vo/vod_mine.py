"""Momente aus Twitch-VODs der Allowlist-Streamer holen (Enis 2026-11-23: „es gibt mehrere VODs“).

Ablauf pro VOD (nur GTA-VODs laut Titel):
1. Nur die Tonspur laden und die lautesten Stellen suchen (Schreien, Lachen, Ausraster = Reaktion).
2. Um jeden Peak ein kurzes Stück Video (1080p) laden, Wörter per Whisper.
3. Pro Moment ein Ordner mit _roh/source.mp4, _roh/words.json und info.json – zum Prüfen und
   Feinschnitt mit `python -m vo compose`. Nichts wird gepostet.
Schon geholte Stellen merkt sich state/vod_mined.json, damit nichts doppelt kommt.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import allowlist
from .common import media_env, read_json, write_json
from .twitch import Helix

GTA_TITLE = re.compile(r"\bgta\b|grand theft auto|vice city|\bgta ?(?:6|vi)\b", re.I)
YTDLP = ["yt-dlp", "--ignore-config", "--no-plugin-dirs", "--no-cache-dir", "--no-playlist",
         "--socket-timeout", "20", "--retries", "3", "--fragment-retries", "3", "--no-progress",
         "--concurrent-fragments", "16"]


def loudness_curve(audio: Path) -> list[float]:
    """Lautheit (RMS in dB) pro Sekunde, von ffmpeg gemessen."""
    res = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(audio), "-vn", "-ac", "1",
                          "-af", "aresample=8000,asetnsamples=n=8000,astats=metadata=1:reset=1,"
                          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                          "-f", "null", "-"], capture_output=True, text=True, check=True, env=media_env())
    out = []
    for m in re.finditer(r"RMS_level=(-?[\d.]+|-inf)", res.stdout):
        out.append(-120.0 if m.group(1) == "-inf" else float(m.group(1)))
    return out


def pick_peaks(curve: list[float], n: int, *, skip_start: int = 600, min_gap: int = 240,
               window: int = 8) -> list[int]:
    """Sekunden mit dem lautesten gleitenden Mittel (über window s), mit Mindestabstand."""
    if len(curve) <= skip_start + window:
        skip_start = 0
    smooth = []
    acc = sum(curve[:window])
    for i in range(len(curve) - window):
        smooth.append((acc / window, i + window // 2))
        acc += curve[i + window] - curve[i]
    chosen: list[int] = []
    for _, t in sorted(smooth, reverse=True):
        if t < skip_start:
            continue
        if all(abs(t - c) >= min_gap for c in chosen):
            chosen.append(t)
        if len(chosen) >= n:
            break
    return sorted(chosen)


def mine(cfg: dict, data: Path, out: Path, *, per_vod: int = 4, vods_per_streamer: int = 2,
         before: int = 30, after: int = 15, logins: list[str] | None = None, client: Helix | None = None,
         whisper=None) -> list[dict]:
    from .render import whisper_words
    whisper = whisper or whisper_words
    client = client or Helix.from_env()
    state_path = data / "state" / "vod_mined.json"
    state = read_json(state_path, {"mined": {}})
    out.mkdir(parents=True, exist_ok=True)
    wanted = [l for l in (logins or allowlist.logins(cfg)) if allowlist.find(cfg, l)]
    rows: list[dict] = []
    for user in client.users(wanted):
        login = user["login"].lower()
        entry = allowlist.find(cfg, login)
        if not entry or allowlist.proof_problem(entry):
            print(f"{login}: keine Freigabe – übersprungen", flush=True)
            continue
        vods = [v for v in client.get("videos", {"user_id": user["id"], "type": "archive", "first": 10})
                if GTA_TITLE.search(v.get("title", ""))][:vods_per_streamer]
        for vod in vods:
            vid, url = vod["id"], vod["url"]
            done = state["mined"].setdefault(vid, [])
            work = data / "vod-work" / vid
            work.mkdir(parents=True, exist_ok=True)
            audio = work / "audio.m4a"
            print(f"{login} {vid}: {vod.get('title', '')[:60]} ({vod.get('duration')})", flush=True)
            try:
                if not audio.is_file():
                    subprocess.run([*YTDLP, "-f", "Audio_Only/bestaudio", "-o", str(audio), "--", url],
                                   check=True, env=media_env(), timeout=1500,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                curve = loudness_curve(audio)
                print(f"{login} {vid}: Ton geladen, {len(curve)} s", flush=True)
            except (subprocess.SubprocessError, OSError) as exc:
                print(f"{login} {vid}: Ton nicht ladbar ({str(exc)[:120]})", flush=True)
                continue
            peaks = [p for p in pick_peaks(curve, per_vod * 3) if all(abs(p - d) > 120 for d in done)][:per_vod]
            for peak in peaks:
                start = max(0, peak - before)
                name = f"{login}_{vid}_{start // 3600:d}h{start % 3600 // 60:02d}m{start % 60:02d}s"
                folder = out / name
                raw = folder / "_roh"
                raw.mkdir(parents=True, exist_ok=True)
                try:
                    subprocess.run([*YTDLP, "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                                    "--download-sections", f"*{start}-{peak + after}",
                                    "--merge-output-format", "mp4", "-o", str(raw / "dl.%(ext)s"), "--", url],
                                   check=True, env=media_env(), timeout=900,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    dl = next(raw.glob("dl.*"))
                    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(dl), "-c:v", "libx264",
                                    "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
                                    str(raw / "source.mp4")], check=True, env=media_env(), timeout=900)
                    dl.unlink()
                except (subprocess.SubprocessError, OSError, StopIteration) as exc:
                    print(f"{name}: Ausschnitt nicht ladbar ({str(exc)[:120]})", flush=True)
                    continue
                words = whisper(raw / "source.mp4", 0.0, float(before + after))
                (raw / "words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
                info = {"streamer": login, "vod": url, "vod_title": vod.get("title", ""),
                        "offset_seconds": start, "peak_seconds": peak, "created_at": vod.get("created_at")}
                write_json(folder / "info.json", info)
                done.append(peak)
                rows.append({"folder": name, **info,
                             "text": " ".join(w["word"] for w in words)[:400]})
                write_json(state_path, state)
    lines = ["# VOD-Momente (Rohmaterial, NICHT posten)", ""]
    for r in rows:
        lines += [f"## {r['folder']}", f"VOD: {r['vod']} (ab {r['offset_seconds']} s) – {r['vod_title']}",
                  "", r["text"] or "(keine Sprache erkannt)", ""]
    (out / "MOMENTE.md").write_text("\n".join(lines), encoding="utf-8")
    return rows
