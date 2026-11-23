"""Schnitt: 9:16-Short (1080×1920, H.264/AAC) mit Hook und optionalen Untertiteln.

Verwendet NUR Dateien, deren Rechte im Brief bestätigt sind:
  rights.type = "own"       → eigene Aufnahme
  rights.type = "licensed"  → schriftliche Freigabe, rights.proof verweist darauf
  rights.type = "clipper_program" → Clip eines Streamers aus der Allowlist (config.json),
                               dessen Clipper-Programm belegt ist (proof im Allowlist-Eintrag)
  rights.type = "synthetic" → technischer Test, wird nie veröffentlicht
Twitch-Clips sind nur mit licensed + proof oder clipper_program gültig.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import allowlist
from .common import media_env

ALLOWED_RIGHTS = {"own", "licensed", "clipper_program", "synthetic"}


class RightsError(RuntimeError):
    pass


def check_rights(brief: dict, cfg: dict | None = None) -> dict:
    rights = brief.get("rights") or {}
    kind = rights.get("type")
    if kind not in ALLOWED_RIGHTS:
        raise RightsError(f"Kein Schnitt: rights.type muss {'/'.join(sorted(ALLOWED_RIGHTS))} sein, ist {kind!r}.")
    if kind == "licensed" and not rights.get("proof"):
        raise RightsError("Kein Schnitt: Für licensed fehlt rights.proof (z. B. Pfad/Link zur Freigabe).")
    if kind == "clipper_program":
        entry = allowlist.find(cfg or {}, brief.get("streamer"))
        if not entry or not entry.get("active", True):
            raise RightsError(f"Kein Schnitt: Streamer {brief.get('streamer')!r} steht nicht (aktiv) in der Allowlist.")
        if not allowlist.has_proof(entry):
            raise RightsError(f"Kein Schnitt: Für {entry['name']} fehlt der Beleg (proof) in config.json "
                              "→ z. B. VOD-Link mit Zeitstempel der Clipper-Ansage.")
        rights = {**rights, "streamer": entry["twitch_login"].lower(), "proof": entry["proof"]}
    if "twitch.tv" in str(brief.get("source", "")) and kind not in {"licensed", "clipper_program"}:
        raise RightsError("Twitch-Material nur mit dokumentierter Freigabe (licensed + proof oder clipper_program).")
    return rights


def _ts(seconds: float) -> str:
    h, rem = divmod(max(seconds, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def write_ass(path: Path, hook: str, subs: list[dict], duration: float, cfg: dict,
              outro: float = 0.0) -> None:
    r = cfg["render"]
    font = r["font"]
    # Ränder so gewählt, dass Texte außerhalb der TikTok-/Shorts-Bedienelemente liegen.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {r['width']}
PlayResY: {r['height']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{font},74,&H00FFFFFF,&H00FFFFFF,&H00A01EFF,&H00A01EFF,1,0,0,0,100,100,0,0,3,18,0,8,90,90,230,1
Style: Mark,{font},34,&H50FFFFFF,&H50FFFFFF,&H80000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,9,40,40,{int(r['height'] * (1 - float(r.get('fg_height_ratio', 0.6))) / 2) + 24},1
Style: Outro,{font},96,&H00FFFFFF,&H00FFFFFF,&H00A01EFF,&H00000000,1,0,0,0,100,100,2,0,1,6,0,5,60,60,0,1
Style: Sub,{font},64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,2,2,110,170,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Hook bleibt die ganze Zeit oben stehen (TikTok-Zuschauer springen sonst nach 2 Sekunden ab).
    hook_end = duration if r.get("hook_whole_clip", True) else min(3.0, duration)
    lines = [f"Dialogue: 1,{_ts(0)},{_ts(hook_end)},Hook,,0,0,0,,{_esc(hook)}"]
    if r.get("watermark"):
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Mark,,0,0,0,,{_esc(r['watermark'])}")
    if outro > 0:
        lines.append(f"Dialogue: 2,{_ts(duration)},{_ts(duration + outro)},Outro,,0,0,0,,"
                     "VICE OVERDRIVE\\N{\\fs52}Folgen für mehr GTA 6")
    for s in subs:
        lines.append(f"Dialogue: 0,{_ts(s['start'])},{_ts(min(s['end'], duration))},Sub,,0,0,0,,{_esc(s['text'])}")
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def parse_srt(path: Path) -> list[dict]:
    blocks = path.read_text(encoding="utf-8-sig").strip().split("\n\n")
    out = []
    for b in blocks:
        rows = b.strip().splitlines()
        if len(rows) < 3 or "-->" not in rows[1]:
            continue
        a, z = [x.strip().replace(",", ".") for x in rows[1].split("-->")]
        def sec(t):
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        out.append({"start": sec(a), "end": sec(z), "text": "\n".join(rows[2:])})
    return out


def probe(path: Path) -> dict:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(path)], text=True, env=media_env())
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {"width": v["width"], "height": v["height"], "video_codec": v["codec_name"],
            "audio_codec": a["codec_name"] if a else None,
            "duration": float(data["format"]["duration"])}


def loudest_moment(src: Path, window: float = 0.5) -> float | None:
    """Zeitpunkt (Sekunden) des lautesten Abschnitts, None ohne Ton oder bei Fehlern."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(src), "-vn", "-af",
             f"asetnsamples=n={int(48000 * window)},aresample=48000,"
             "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
             "-f", "null", "-"], capture_output=True, text=True, timeout=300, env=media_env()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    best, t, best_t = None, None, None
    for line in out.splitlines():
        if "pts_time:" in line:
            t = float(line.rsplit("pts_time:", 1)[1])
        elif "RMS_level=" in line and t is not None:
            try:
                v = float(line.split("=", 1)[1])
            except ValueError:
                continue
            if best is None or v > best:
                best, best_t = v, t
    return best_t


def auto_subtitles(src: Path, start: float, duration: float, model: str = "small") -> list[dict]:
    """Deutsche Untertitel per faster-whisper (lokal, kostenlos). Leer, wenn nicht installiert."""
    try:
        from faster_whisper import WhisperModel  # nur im Actions-Runner installiert
    except ImportError:
        return []
    try:
        import numpy as np
        # Ton selbst mit ffmpeg dekodieren (16 kHz mono), dann braucht faster-whisper kein PyAV.
        raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", str(start), "-t", str(duration),
                              "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                             capture_output=True, check=True, timeout=300, env=media_env()).stdout
        audio = np.frombuffer(raw, dtype=np.float32)
        segs, _ = WhisperModel(model, device="cpu", compute_type="int8").transcribe(
            audio, language="de", vad_filter=True, word_timestamps=True)
        words = [w for seg in segs for w in (seg.words or [])]
    except Exception as exc:  # Untertitel sind ein Extra, kein Grund für einen Abbruch
        print(f"Untertitel übersprungen: {str(exc)[:200]}", flush=True)
        return []
    # Kurze Häppchen (max. 4 Wörter), gut lesbar auf dem Handy.
    out, chunk = [], []
    for w in words:
        chunk.append(w)
        if len(chunk) == 4 or w.word.strip().endswith((".", "!", "?", ",")):
            out.append(chunk)
            chunk = []
    if chunk:
        out.append(chunk)
    return [{"start": max(0.0, c[0].start), "end": max(0.0, c[-1].end),
             "text": " ".join(x.word.strip() for x in c)} for c in out if c[-1].end > c[0].start]


def teaser_window(peak: float | None, start: float, duration: float, length: float) -> tuple[float, float] | None:
    """Stärkster Moment als kurzer Vorspann, wenn er nicht ohnehin in den ersten Sekunden liegt."""
    if peak is None or length <= 0 or peak - start < 4.0 or peak > start + duration:
        return None
    t0 = max(start, peak - length / 2)
    return t0, length


def render_short(brief: dict, hook: str, out_dir: Path, cfg: dict, base_dir: Path,
                 *, require_subtitles: bool = True) -> dict:
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise SystemExit(f"{binary} fehlt.")
    rights = check_rights(brief, cfg)
    r = cfg["render"]
    src = (base_dir / brief["source"]).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Quelldatei fehlt: {src}")
    start = float(brief.get("start", 0))
    duration = min(float(brief.get("duration", r["max_seconds"])), float(r["max_seconds"]))
    src_info = probe(src)
    duration = max(0.1, min(duration, src_info["duration"] - start))
    subs = brief.get("subtitles") or []
    if brief.get("subtitles_srt"):
        subs = parse_srt(base_dir / brief["subtitles_srt"])
    if not subs and r.get("auto_subtitles"):
        subs = auto_subtitles(src, start, duration, r.get("whisper_model", "small"))
    if require_subtitles and not subs:
        raise ValueError("Untertitel fehlen (subtitles oder subtitles_srt im Brief).")

    out_dir.mkdir(parents=True, exist_ok=True)
    W, H = r["width"], r["height"]
    has_audio = src_info["audio_codec"] is not None
    teaser = None
    if has_audio and r.get("teaser_seconds", 1.5) > 0:
        teaser = teaser_window(loudest_moment(src), start, duration, float(r.get("teaser_seconds", 1.5)))
    total = duration
    if teaser:
        duration = min(duration, float(r["max_seconds"]) - teaser[1])
        total = duration + teaser[1]
        subs = [{**x, "start": x["start"] + teaser[1], "end": x["end"] + teaser[1]} for x in subs]
    outro = float(r.get("outro_seconds", 0) or 0)
    if total < 5 * outro:  # sehr kurze Clips ohne Abspann
        outro = 0.0
    if total + outro > float(r["max_seconds"]):
        cut = total + outro - float(r["max_seconds"])
        duration -= cut
        total -= cut
    write_ass(out_dir / "subs.ass", hook, subs, total, cfg, outro)
    # Gesamtes Originalbild proportional einpassen: kein Center-Crop. Dadurch bleibt eine im
    # Quellbild vorhandene Facecam auch bei Querformat-Clips im fertigen 9:16-Short sichtbar.
    # Kein schwarzes Pad: der unscharfe Hintergrund füllt die freien Flächen oben/unten.
    fg_h = int(H * float(r.get("fg_height_ratio", 0.6))) // 2 * 2
    if teaser:
        head = ("[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[cv][ca];"
                "[cv]setpts=PTS-STARTPTS,split=2[bg][fg];")
    else:
        head = "[0:v]split=2[bg][fg];"
    vf = (
        head +
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.12[bgb];"
        f"[fg]scale={W}:{fg_h}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
        + (f",tpad=stop_duration={outro}:stop_mode=add:color={r.get('background', 'black')}" if outro > 0 else "")
        + ",ass=subs.ass,format=yuv420p[v]"
    )
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if teaser:
        cmd += ["-ss", str(teaser[0]), "-t", str(teaser[1]), "-i", str(src)]
    cmd += ["-ss", str(start), "-t", str(duration), "-i", str(src)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo"]
    audio_map = "[ca]" if teaser else ("0:a:0" if has_audio else "1:a:0")
    if outro > 0:
        vf += f";{audio_map if audio_map.startswith('[') else '[' + audio_map + ']'}apad=pad_dur={outro}[pa]"
        audio_map = "[pa]"
    video_limit = r.get("max_video_bitrate")
    vbv = ["-maxrate", video_limit, "-bufsize", video_limit] if video_limit else []
    cmd += ["-filter_complex", vf, "-map", "[v]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "30", *vbv,
            "-t", str(total + outro), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
            "short.mp4"]
    subprocess.run(cmd, cwd=out_dir, check=True, env=media_env())
    info = probe(out_dir / "short.mp4")
    if (info["width"], info["height"], info["video_codec"]) != (W, H, "h264"):
        raise RuntimeError(f"Unerwartetes Videoformat: {info}")
    return {"video": info, "rights": rights, "file": "short.mp4"}
