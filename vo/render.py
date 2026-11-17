"""Schnitt: 9:16-Short (1080×1920, H.264/AAC) mit Hook oben und eingebrannten deutschen Untertiteln.

Verwendet NUR Dateien, deren Rechte im Brief bestätigt sind:
  rights.type = "own"       → eigene Aufnahme
  rights.type = "licensed"  → schriftliche Freigabe, rights.proof verweist darauf
  rights.type = "synthetic" → technischer Test, wird nie veröffentlicht
Twitch-Clips aus dem Radar sind KEINE gültige Quelle, solange keine Freigabe vorliegt.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ALLOWED_RIGHTS = {"own", "licensed", "synthetic"}


class RightsError(RuntimeError):
    pass


def check_rights(brief: dict) -> dict:
    rights = brief.get("rights") or {}
    kind = rights.get("type")
    if kind not in ALLOWED_RIGHTS:
        raise RightsError(f"Kein Schnitt: rights.type muss own/licensed/synthetic sein, ist {kind!r}.")
    if kind == "licensed" and not rights.get("proof"):
        raise RightsError("Kein Schnitt: Für licensed fehlt rights.proof (z. B. Pfad/Link zur Freigabe).")
    if "twitch.tv" in str(brief.get("source", "")) and kind != "licensed":
        raise RightsError("Twitch-Material nur mit dokumentierter Freigabe (licensed + proof).")
    return rights


def _ts(seconds: float) -> str:
    h, rem = divmod(max(seconds, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def write_ass(path: Path, hook: str, subs: list[dict], duration: float, cfg: dict) -> None:
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
Style: Sub,{font},64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,6,2,2,110,170,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 1,{_ts(0)},{_ts(min(3.0, duration))},Hook,,0,0,0,,{_esc(hook)}"]
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
        "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(path)], text=True)
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {"width": v["width"], "height": v["height"], "video_codec": v["codec_name"],
            "audio_codec": a["codec_name"] if a else None,
            "duration": float(data["format"]["duration"])}


def render_short(brief: dict, hook: str, out_dir: Path, cfg: dict, base_dir: Path) -> dict:
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise SystemExit(f"{binary} fehlt.")
    rights = check_rights(brief)
    r = cfg["render"]
    src = (base_dir / brief["source"]).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Quelldatei fehlt: {src}")
    start = float(brief.get("start", 0))
    duration = min(float(brief.get("duration", r["max_seconds"])), float(r["max_seconds"]))
    subs = brief.get("subtitles") or []
    if brief.get("subtitles_srt"):
        subs = parse_srt(base_dir / brief["subtitles_srt"])
    if not subs:
        raise ValueError("Untertitel fehlen (subtitles oder subtitles_srt im Brief).")

    out_dir.mkdir(parents=True, exist_ok=True)
    write_ass(out_dir / "subs.ass", hook, subs, duration, cfg)
    W, H = r["width"], r["height"]
    vf = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.12[bgb];"
        f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,ass=subs.ass,format=yuv420p[v]"
    )
    has_audio = probe(src)["audio_codec"] is not None
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-ss", str(start), "-t", str(duration), "-i", str(src)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-filter_complex", vf, "-map", "[v]", "-map", "0:a:0" if has_audio else "1:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "30",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
            "-shortest", "short.mp4"]
    subprocess.run(cmd, cwd=out_dir, check=True)
    info = probe(out_dir / "short.mp4")
    if (info["width"], info["height"], info["video_codec"]) != (W, H, "h264"):
        raise RuntimeError(f"Unerwartetes Videoformat: {info}")
    return {"video": info, "rights": rights, "file": "short.mp4"}
