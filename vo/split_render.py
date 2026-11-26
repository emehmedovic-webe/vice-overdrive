"""Format v3 (Enis 2026-11-23): Facecam oben, Gameplay unten, eigener Text und Abspann.

Aufbau 1080x1920 ohne Balken und ohne Bewegungseffekte:
- oben 1080x750: Facecam des Streamers (Ausschnitt aus dem Originalbild)
- unten 1080x1170: Gameplay-Ausschnitt in voller Höhe
- auf der Naht: weiße TikTok-Textbox mit schwarzem Satz (Überschrift, ganzer Clip sichtbar)
- groß, Wort für Wort: die exakt gesprochenen Wörter (Whisper-Zeitstempel), nichts erfunden
- optional eigene Kommentar-Blasen und eine Pointe
- danach Abspann: Supercar-Artwork + Logo + „FOLGE FÜR MEHR CONTENT“ + @VICEOVERDRIVE
Originalton bleibt.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from .common import media_env

W, H = 1080, 1920
CAM_H = 750
GAME_H = H - CAM_H
# Stil "pip": Facecam-Kasten oben, Überschrift darunter.
PIP_W, PIP_MAX_H, PIP_Y = 760, 560, 110
PIP_HEAD_Y = 760
ASSETS = Path(__file__).resolve().parent.parent / "assets" / "outro"

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Head,{font},58,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,1,0,0,0,100,100,0,0,3,20,0,5,60,60,0,1
Style: Word,{font},92,&H0000E6FF,&H0000E6FF,&H00000000,&H96000000,1,0,0,0,100,100,2,0,1,10,6,5,40,40,0,1
Style: Bubble,{font},54,&H00180A20,&H00180A20,&H00FFFFFF,&H00FFFFFF,1,0,0,0,100,100,0,0,3,20,0,5,80,80,0,1
Style: Punch,{font},140,&H0000E6FF,&H0000E6FF,&H00000000,&H96000000,1,0,0,0,100,100,2,0,1,12,8,5,40,40,0,1
Style: Big,{font},96,&H00FFFFFF,&H00FFFFFF,&H00A01EFF,&H96000000,1,0,0,0,100,100,4,0,1,6,5,5,40,40,0,1
Style: Hook,{font},60,&H00000000,&H00000000,&H0000E6FF,&H0000E6FF,1,0,0,0,100,100,0,0,3,24,0,5,60,60,0,1
Style: HeadDark,{font},56,&H00FFFFFF,&H00FFFFFF,&H00140A0A,&H00140A0A,1,0,0,0,100,100,0,0,3,20,0,5,60,60,0,1
Style: HeadFrame,{font},56,&HFF000000,&HFF000000,&H00A01EFF,&H00A01EFF,1,0,0,0,100,100,0,0,3,26,0,5,60,60,0,1
Style: HeadLight,{font},56,&H00141414,&H00141414,&H00FFFFFF,&H00FFFFFF,1,0,0,0,100,100,0,0,3,20,0,5,60,60,0,1
Style: HeadClean,{font},66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,1,0,1,7,4,5,60,60,0,1
Style: Small,{font},52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,6,0,1,4,3,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(s: float) -> str:
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u2049\u203C]+")


def _esc(text: str) -> str:
    # Emojis rendert libass nicht sauber (Enis 2026-11-26: „man erkennt die Smileys nicht“) – im Bildtext weglassen.
    text = censor(text).replace("\u2049", "?!").replace("\u203C", "!!")
    text = re.sub(r" *\n *", "\n", re.sub(r" {2,}", " ", _EMOJI.sub("", text))).strip()
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def wrap(text: str, width: int = 30) -> str:
    """Höchstens zwei Zeilen, an Wortgrenzen möglichst gleich lang."""
    words = text.split()
    if len(text) <= width or len(words) < 2:
        return text
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


# Schimpfwörter zensieren (Enis 2026-11-26): Anfangsbuchstabe bleibt, Rest Sternchen – Untertitel, Hook, Überschrift, Caption.
_SWEAR = re.compile(r"\b(?:\w*(?:schei(?:ß|ss|s)\w*|fick\w*|gefickt\w*|fotze\w*|hurensohn\w*|huren\w*|hure|wichser\w*|"
                    r"arschloch\w*|arsch|bastard\w*|missgeburt\w*|schlampe\w*|spast\w*|behindert\w*|"
                    r"fuck\w*|shit\w*|bitch\w*|motherfucker\w*))\b", re.IGNORECASE)


def censor(text: str) -> str:
    return _SWEAR.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), text)


def word_events(words: list[dict], start: float, end: float, blocked: list[tuple[float, float]]) -> list[tuple]:
    """Ein Ereignis je gesprochenem Wort (exakter Wortlaut, nur Großschreibung und Satzzeichen-Trim)."""
    inside = [w for w in words if start <= float(w["start"]) < end and str(w.get("word", "")).strip()]
    events = []
    for i, w in enumerate(inside):
        t0 = float(w["start"]) - start
        nxt = float(inside[i + 1]["start"]) - start if i + 1 < len(inside) else end - start
        t1 = min(nxt, float(w["end"]) - start + 0.35, t0 + 1.2)
        if t1 - t0 < 0.08 or any(a < t1 and t0 < b for a, b in blocked):
            continue
        text = censor(re.sub(r"^[\s\"„“'(]+|[\s\"„“'),;:]+$", "", str(w["word"]))).upper()
        if text:
            events.append((t0, t1, text))
    return events


def write_body_ass(path: Path, *, headline: str, duration: float, words: list[dict], start: float,
                   bubbles: list[dict] = (), punch: list[dict] = (), font: str = "Inter Display",
                   head_y: int = CAM_H, hook: dict | None = None, head_style: str = "white") -> None:
    lines = [_HEADER.format(font=font)]
    if hook and hook.get("text"):
        # Hook in den ersten Sekunden (Enis 2026-11-26): groß, gelber Kasten, oben im Gameplay, ohne Animation.
        lines.append(f"Dialogue: 5,{_ts(0)},{_ts(min(2.0, float(hook.get('seconds', 2.0))))},Hook,,0,0,0,,"
                     f"{{\\pos(540,{head_y if hook.get('pos') == 'divider' else head_y + 230})}}{_esc(wrap(hook['text'], 22))}")
    if headline.strip():
        lines.extend(_headline_events(headline, duration, head_y, head_style))
    for b in bubbles:
        lines.append(f"Dialogue: 3,{_ts(b['start'])},{_ts(b['end'])},Bubble,,0,0,0,,"
                     f"{{\\pos(540,1700)}}{_esc(wrap(b['text'], 32))}")
    blocked = []
    for p in punch:
        blocked.append((float(p["start"]), float(p["end"])))
        lines.append(f"Dialogue: 4,{_ts(p['start'])},{_ts(p['end'])},Punch,,0,0,0,,"
                     f"{{\\pos(540,1450)\\frz-5}}{_esc(wrap(p['text'].upper(), 12))}")
    for t0, t1, text in word_events(words, start, start + duration, blocked):
        lines.append(f"Dialogue: 4,{_ts(t0)},{_ts(t1)},Word,,0,0,0,,{{\\pos(540,1450)}}{_esc(text)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Überschrift-Designs (Enis 2026-11-26: Boxen schöner). Erstes Wort (Streamername) farbig hervorgehoben.
_PINK, _YELLOW = "&HA01EFF&", "&H00E6FF&"


def _headline_events(headline: str, duration: float, head_y: int, style: str) -> list[str]:
    text = _esc(wrap(headline))
    first, _, rest = text.partition(" ")
    span = f"0,{_ts(0)},{_ts(duration)}"
    pos = f"{{\\pos(540,{head_y})}}"
    if style == "dark":  # schwarzer Kasten, pinker Rahmen, Name pink
        return [f"Dialogue: 1,{span[2:]},HeadFrame,,0,0,0,,{pos}{text}",
                f"Dialogue: 2,{span[2:]},HeadDark,,0,0,0,,{pos}{{\\1c{_PINK}}}{first}{{\\1c&HFFFFFF&}} {rest}"]
    if style == "light":  # weißer Kasten, pinker Rahmen, Name pink
        return [f"Dialogue: 1,{span[2:]},HeadFrame,,0,0,0,,{pos}{text}",
                f"Dialogue: 2,{span[2:]},HeadLight,,0,0,0,,{pos}{{\\1c{_PINK}}}{first}{{\\1c&H141414&}} {rest}"]
    if style == "clean":  # ohne Kasten, weiße Schrift mit Kontur, Name gelb
        return [f"Dialogue: 2,{span[2:]},HeadClean,,0,0,0,,{pos}{{\\1c{_YELLOW}}}{first}{{\\1c&HFFFFFF&}} {rest}"]
    return [f"Dialogue: 2,{span[2:]},Head,,0,0,0,,{pos}{text}"]


def write_outro_ass(path: Path, seconds: float, font: str = "Inter Display") -> None:
    end = _ts(seconds)
    path.write_text(_HEADER.format(font=font) + "\n".join([
        f"Dialogue: 1,0:00:00.00,{end},Big,,0,0,0,,{{\\pos(540,1430)\\fscx50\\fscy50\\t(0,220,\\fscx106\\fscy106)"
        f"\\t(220,340,\\fscx100\\fscy100)}}FOLGE FÜR MEHR",
        f"Dialogue: 1,0:00:00.00,{end},Big,,0,0,0,,{{\\pos(540,1545)\\1c&H00E6FF&\\alpha&HFF&\\t(150,300,\\alpha&H00&)"
        f"\\fscx50\\fscy50\\t(150,370,\\fscx106\\fscy106)\\t(370,490,\\fscx100\\fscy100)}}CONTENT",
        f"Dialogue: 1,0:00:00.00,{end},Small,,0,0,0,,{{\\pos(540,1670)\\alpha&HFF&\\t(400,650,\\alpha&H00&)}}@VICEOVERDRIVE",
    ]) + "\n", encoding="utf-8")


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *cmd],
                   cwd=cwd, check=True, env=media_env())


def render_split(src: Path, out: Path, *, start: float, duration: float, facecam: dict, headline: str,
                 words: list[dict] = (), bubbles: list[dict] = (), punch: list[dict] = (),
                 game_x: float | None = None, blur: list[dict] = (), outro_seconds: float = 2.5, font: str = "Inter Display",
                 max_bitrate: str = "6M", layout: str = "split", hook: dict | None = None,
                 head_style: str = "white") -> Path:
    """facecam = {x, y, w, h} im auf 1920x1080 skalierten Quellbild. game_x = linker Rand des Gameplay-Ausschnitts.

    layout "split": Facecam oben (1080x750), Gameplay unten.
    layout "pip": Gameplay im ganzen Bild, Facecam komplett als Kasten oben (Enis 2026-11-23: Stil abwechseln,
    Streamer immer ganz sichtbar).
    """
    if layout == "pip":
        gw = 608  # 9:16 aus 1080 Höhe
        gx = int(max(0, min(1920 - gw, (1920 - gw) / 2 if game_x is None else game_x)))
        return _render(src, out, start=start, duration=duration, facecam=facecam, headline=headline, words=words,
                       bubbles=bubbles, punch=punch, blur=blur, outro_seconds=outro_seconds, font=font,
                       max_bitrate=max_bitrate, head_y=PIP_HEAD_Y, hook=hook, head_style=head_style,
                       layout_vf=lambda fx, fy, fw, fh: (
                           f"[s2]crop={gw}:1080:{gx}:0,scale={W}:{H}[game];"
                           f"[s1]crop={fw}:{fh}:{fx}:{fy},scale={PIP_W}:{PIP_MAX_H}:force_original_aspect_ratio=decrease,"
                           f"pad=iw+16:ih+16:8:8:white[cam];"
                           f"[game][cam]overlay=(W-w)/2:{PIP_Y}"))
    gw = round(1080 * W / GAME_H) // 2 * 2  # 997 → Seitenverhältnis 1080:1170
    gx = int(max(0, min(1920 - gw, (1920 - gw) / 2 if game_x is None else game_x)))
    return _render(src, out, start=start, duration=duration, facecam=facecam, headline=headline, words=words,
                   bubbles=bubbles, punch=punch, blur=blur, outro_seconds=outro_seconds, font=font,
                   max_bitrate=max_bitrate, head_y=CAM_H, hook=hook, head_style=head_style,
                   layout_vf=lambda fx, fy, fw, fh: (
                       # Ganze Facecam einpassen (nichts abschneiden), Rand mit unscharfer Kopie füllen.
                       f"[s1]crop={fw}:{fh}:{fx}:{fy},split[c1][c2];"
                       f"[c1]scale={W}:{CAM_H}:force_original_aspect_ratio=increase,crop={W}:{CAM_H},"
                       f"boxblur=25:2,eq=brightness=-0.2[cbg];"
                       f"[c2]scale={W}:{CAM_H}:force_original_aspect_ratio=decrease[cfg];"
                       f"[cbg][cfg]overlay=(W-w)/2:(H-h)/2[cam];"
                       f"[s2]crop={gw}:1080:{gx}:0,scale={W}:{GAME_H}[game];"
                       f"[cam][game]vstack"))


def _render(src: Path, out: Path, *, start, duration, facecam, headline, words, bubbles, punch, blur,
            outro_seconds, font, max_bitrate, head_y, layout_vf, hook=None, head_style="white") -> Path:
    src, out = Path(src).resolve(), Path(out).resolve()
    fx, fy, fw, fh = (int(facecam[k]) for k in ("x", "y", "w", "h"))
    with tempfile.TemporaryDirectory(prefix="vo-split-") as tmp:
        t = Path(tmp)
        write_body_ass(t / "body.ass", headline=headline, duration=duration, words=list(words), start=start,
                       bubbles=list(bubbles), punch=list(punch), font=font, head_y=head_y, hook=hook,
                       head_style=head_style)
        # Eingebrannte Fremd-Untertitel o. Ä. unkenntlich machen (Boxen im 1920x1080-Bild).
        pre = "[0:v]scale=1920:1080,setsar=1"
        for i, bx in enumerate(blur):
            x, y, w, h = (int(bx[k]) for k in ("x", "y", "w", "h"))
            pre += (f"[p{i}];[p{i}]split[q{i}][r{i}];[r{i}]crop={w}:{h}:{x}:{y},boxblur=20:3[b{i}];"
                    f"[q{i}][b{i}]overlay={x}:{y}")
        vf = (f"{pre},split[s1][s2];" + layout_vf(fx, fy, fw, fh)
              + ",ass=body.ass,fps=30,setsar=1,format=yuv420p[v]")
        enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", max_bitrate,
               "-bufsize", max_bitrate, "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
        has_audio = bool(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
             str(src)], capture_output=True, text=True, env=media_env()).stdout.strip())
        mix = ";[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]" if has_audio else ";[1:a]anull[a]"
        _run(["-ss", str(start), "-t", str(duration), "-i", str(src),
              "-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo",
              "-filter_complex", vf + mix,
              "-map", "[v]", "-map", "[a]", "-t", str(duration), *enc, "body.mp4"], t)
        parts = ["body.mp4"]
        if outro_seconds > 0:
            write_outro_ass(t / "outro.ass", outro_seconds, font)
            of = ("[0:v]split[c1][c2];[c1]scale=-2:1920,crop=1080:1920,boxblur=30:2,eq=brightness=-0.25[bg];"
                  "[c2]scale=1080:-2[img];[bg][img]overlay=0:(H-h)/2-60[b2];[1:v]scale=330:-1[lg];"
                  "[b2][lg]overlay=(W-w)/2:200,fps=30,ass=outro.ass,setsar=1,format=yuv420p[v]")
            _run(["-loop", "1", "-t", str(outro_seconds), "-i", str(ASSETS / "car.jpg"),
                  "-loop", "1", "-t", str(outro_seconds), "-i", str(ASSETS / "logo.png"),
                  "-f", "lavfi", "-t", str(outro_seconds), "-i", "anullsrc=r=48000:cl=stereo",
                  "-filter_complex", of, "-map", "[v]", "-map", "2:a", "-t", str(outro_seconds), *enc,
                  "outro.mp4"], t)
            parts.append("outro.mp4")
        inputs = [x for p in parts for x in ("-i", p)]
        n = len(parts)
        concat = "".join(f"[{i}:v]setsar=1[v{i}];" for i in range(n)) + "".join(f"[v{i}][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        _run([*inputs, "-filter_complex", concat, "-map", "[v]", "-map", "[a]", *enc,
              "-movflags", "+faststart", str(out)], t)
    return out


def load_words(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else []
