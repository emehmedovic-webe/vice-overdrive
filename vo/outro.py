"""Abspann im Vice-City-Stil (eigene Grafik, keine Rockstar-Assets): Sonnenuntergang,
Retro-Sonne, Skyline, Palmen, Meer – darauf das VICE-OVERDRIVE-Logo und „FOLGE FÜR MEHR CONTENT“.

Erzeugt einmalig ein Hintergrundbild und daraus ein kurzes Outro-Video, das render_short
an jeden Clip hängt.
"""
from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1080, 1920
HORIZON = 1240


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _sky() -> np.ndarray:
    stops = [(0, (18, 6, 48)), (520, (74, 18, 112)), (900, (214, 46, 128)), (1120, (255, 122, 92)),
             (HORIZON, (255, 190, 110))]
    img = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(HORIZON):
        for (y0, c0), (y1, c1) in zip(stops, stops[1:]):
            if y0 <= y <= y1:
                img[y, :] = _lerp(c0, c1, (y - y0) / max(1, y1 - y0))
                break
    for y in range(HORIZON, H):  # Meer: dunkles Violett, nach unten dunkler
        t = (y - HORIZON) / (H - HORIZON)
        img[y, :] = _lerp((70, 20, 96), (12, 4, 30), t)
    return img


def _sun(draw: ImageDraw.ImageDraw, layer: Image.Image) -> None:
    cx, cy, r = W // 2, HORIZON - 150, 330
    sun = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = sun.load()
    for y in range(cy - r, HORIZON):
        dy = y - cy
        if abs(dy) > r:
            continue
        half = int(math.sqrt(r * r - dy * dy))
        t = (y - (cy - r)) / (2 * r)
        col = _lerp((255, 236, 120), (255, 64, 150), t)
        # Retro-Streifen in der unteren Hälfte, nach unten breiter
        if dy > 20:
            band = 34 - int(dy / 12)
            gap = 4 + int((dy - 20) / 22)
            if (dy % max(band, 12)) < gap:
                continue
        for x in range(cx - half, cx + half):
            px[x, y] = (*col, 255)
    glow = sun.filter(ImageFilter.GaussianBlur(40))
    layer.alpha_composite(glow)
    layer.alpha_composite(sun)


def _skyline(draw: ImageDraw.ImageDraw, rnd: random.Random) -> None:
    x = 0
    while x < W:
        w = rnd.randint(28, 70)
        h = rnd.randint(40, 230) if not (380 < x < 700) else rnd.randint(20, 90)
        draw.rectangle([x, HORIZON - h, x + w, HORIZON], fill=(38, 10, 58, 255))
        for wy in range(HORIZON - h + 12, HORIZON - 8, 18):  # ein paar Fenster
            for wx in range(x + 6, x + w - 6, 14):
                if rnd.random() < 0.18:
                    draw.rectangle([wx, wy, wx + 4, wy + 6], fill=(255, 140, 200, 200))
        x += w + rnd.randint(0, 6)


def _palm(draw: ImageDraw.ImageDraw, base_x: int, base_y: int, height: int, lean: float, s: float) -> None:
    col = (16, 4, 30, 255)
    pts = []
    for i in range(41):
        t = i / 40
        pts.append((base_x + lean * height * t * t, base_y - height * t))
    for i in range(40):
        wdt = (22 - 12 * i / 40) * s
        draw.line([pts[i], pts[i + 1]], fill=col, width=int(wdt))
    top = pts[-1]
    for ang in (-170, -140, -110, -70, -40, -10, 20, 200, 160):
        a = math.radians(ang)
        length = 260 * s
        frond = []
        for k in range(21):
            t = k / 20
            x = top[0] + math.cos(a) * length * t
            y = top[1] + math.sin(a) * length * t + 120 * s * t * t  # hängt nach unten
            frond.append((x, y))
        for k in range(20):
            wdt = max(2, int(26 * s * math.sin(math.pi * (k + 1) / 21)))
            draw.line([frond[k], frond[k + 1]], fill=col, width=wdt)
        for k in range(4, 19, 3):  # Fiederblätter
            x, y = frond[k]
            for side in (-1, 1):
                draw.line([(x, y), (x + side * 14 * s, y + 30 * s)], fill=col, width=max(2, int(4 * s)))
    draw.ellipse([top[0] - 18 * s, top[1] - 12 * s, top[0] + 18 * s, top[1] + 20 * s], fill=col)


def background(path: Path) -> Path:
    rnd = random.Random(6)
    base = Image.fromarray(_sky()).convert("RGBA")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _sun(ImageDraw.Draw(layer), layer)
    base.alpha_composite(layer)
    d = ImageDraw.Draw(base)
    _skyline(d, rnd)
    # Spiegelung im Wasser: Sonne/Skyline gestaucht, verwischt, mit Wellenlinien
    top = base.crop((0, HORIZON - 480, W, HORIZON)).transpose(Image.FLIP_TOP_BOTTOM)
    top = top.resize((W, 300)).filter(ImageFilter.GaussianBlur(6))
    mask = Image.linear_gradient("L").resize((W, 300)).point(lambda v: int((255 - v) * 0.55))
    base.paste(top, (0, HORIZON), mask)
    for y in range(HORIZON + 8, H, 26):
        d.line([(0, y), (W, y)], fill=(20, 6, 40, 90), width=3)
    _palm(d, -40, H - 120, 1250, 0.32, 1.25)
    _palm(d, 1150, H - 60, 1100, -0.30, 1.1)
    path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(path)
    return path


def round_logo(src: Path, path: Path, size: int = 560) -> Path:
    logo = Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([10, 10, size * 4 - 10, size * 4 - 10], fill=255)
    logo.putalpha(mask.resize((size, size), Image.LANCZOS))
    ring = Image.new("RGBA", (size + 60, size + 60), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse([6, 6, size + 54, size + 54], outline=(255, 60, 170, 255), width=14)
    glow = ring.filter(ImageFilter.GaussianBlur(14))
    out = Image.new("RGBA", ring.size, (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(glow)
    out.alpha_composite(ring)
    out.alpha_composite(logo, (30, 30))
    out.save(path)
    return path


def outro_ass(path: Path, seconds: float, font: str) -> Path:
    ms = int(seconds * 1000)
    end = f"0:00:{seconds:05.2f}"
    path.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Big,{font},92,&H00FFFFFF,&H00FFFFFF,&H00A01EFF,&H96000000,1,0,0,0,100,100,4,0,1,5,5,5,40,40,0,1
Style: Small,{font},54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,6,0,1,4,3,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,0:00:00.00,{end},Big,,0,0,0,,{{\\pos({W // 2},1210)\\alpha&HFF&\\t(380,620,\\alpha&H00&)\\fscx60\\fscy60\\t(380,620,\\fscx104\\fscy104)\\t(620,760,\\fscx100\\fscy100)}}FOLGE FÜR MEHR
Dialogue: 1,0:00:00.00,{end},Big,,0,0,0,,{{\\pos({W // 2},1320)\\1c&H00E6FF&\\alpha&HFF&\\t(560,800,\\alpha&H00&)\\fscx60\\fscy60\\t(560,800,\\fscx106\\fscy106)\\t(800,940,\\fscx100\\fscy100)}}CONTENT
Dialogue: 1,0:00:00.00,{end},Small,,0,0,0,,{{\\pos({W // 2},1450)\\alpha&HFF&\\t(900,{min(ms, 1200)},\\alpha&H00&)}}@VICEOVERDRIVE
""", encoding="utf-8")
    return path


def make_outro(logo_src: Path, out: Path, seconds: float = 2.5, font: str = "Inter Display") -> Path:
    work = out.parent
    bg = background(work / "outro_bg.png")
    logo = round_logo(logo_src, work / "outro_logo.png")
    ass = outro_ass(work / "outro.ass", seconds, font)
    # Hintergrund zoomt langsam rein; Logo plumpst mit Überschwinger in die Mitte.
    vf = (f"[0:v]scale={W * 2}:{H * 2},zoompan=z='1+0.04*on/({seconds}*30)':x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30[bg];"
          f"[1:v]format=rgba,scale=w='if(lt(t,0.35),620*(0.3+2*t),if(lt(t,0.5),620*(1.0+0.3*(0.5-t)),620))':"
          f"h=-1:eval=frame[lg];"
          f"[bg][lg]overlay=x='(W-w)/2':y='560-h/2':eval=frame,ass={ass.name},format=yuv420p[v]")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-loop", "1", "-t", str(seconds), "-i", bg.name, "-loop", "1", "-t", str(seconds), "-i", logo.name,
           "-f", "lavfi", "-t", str(seconds), "-i", "anullsrc=r=48000:cl=stereo",
           "-filter_complex", vf, "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", str(seconds), out.name]
    subprocess.run(cmd, cwd=work, check=True)
    return out
