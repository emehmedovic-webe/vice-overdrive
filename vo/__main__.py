"""Kommandozeile:

  python -m vo radar                       Twitch-Radar (braucht TWITCH_CLIENT_ID/SECRET)
  python -m vo make briefs/<datei>.json    Short aus eigener/lizenzierter Datei schneiden
  python -m vo batch                       Freigabe-Batch für alle offenen Shorts anlegen
  python -m vo publish youtube|tiktok      Dry-Run (Standard); --live nur nach Freigabe
  python -m vo selftest                    Offline-Ende-zu-Ende-Test mit synthetischem Video
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from .common import ROOT, iso, load_config, now_utc, write_json
from .publish import make_batch, publish
from .render import render_short
from .texts import build_texts


def cmd_make(brief_path: Path, cfg: dict, shorts_root: Path) -> Path:
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    short_id = brief.get("id") or re.sub(r"[^a-z0-9]+", "-", brief_path.stem.lower())
    texts = build_texts(brief, cfg)
    out = shorts_root / short_id
    result = render_short(brief, texts["hook"], out, cfg, brief_path.parent)
    manifest = {"short_id": short_id, "created_at": iso(now_utc()),
                "synthetic": result["rights"]["type"] == "synthetic",
                "source": brief["source"], "rights": result["rights"], "file": result["file"],
                "video": result["video"], "texts": texts, "published": {}}
    if brief.get("public_video_url"):
        manifest["public_video_url"] = brief["public_video_url"]
    write_json(out / "manifest.json", manifest)
    (out / "youtube.txt").write_text(f"{texts['youtube']['title']}\n\n{texts['youtube']['description']}\n", encoding="utf-8")
    (out / "tiktok.txt").write_text(texts["tiktok"]["caption"] + "\n", encoding="utf-8")
    print(f"Short fertig: {out/'short.mp4'} ({result['video']})")
    return out


def selftest(cfg: dict, work: Path) -> None:
    """Erzeugt ein synthetisches Quellvideo (16:9 mit Ton), schneidet es zum Short und prüft alles."""
    work.mkdir(parents=True, exist_ok=True)
    src = work / "synthetic-source.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "8", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    brief = {"id": "selftest-synthetic", "source": src.name, "start": 1, "duration": 6,
             "rights": {"type": "synthetic", "note": "Testbild, nie posten"},
             "topic": "Technischer Test", "hook": "TEST · Nicht posten",
             "keywords": ["Test"],
             "subtitles": [{"start": 0.2, "end": 2.8, "text": "Das ist ein technischer Test."},
                           {"start": 3.0, "end": 5.8, "text": "Größe, Übergänge & Umlaute: äöü ß"}]}
    bp = work / "selftest.json"
    write_json(bp, brief)
    shorts = work / "shorts"
    out = cmd_make(bp, cfg, shorts)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    v = m["video"]
    assert (v["width"], v["height"], v["video_codec"], v["audio_codec"]) == (1080, 1920, "h264", "aac"), v
    assert 5.5 <= v["duration"] <= 6.5, v
    assert m["texts"]["youtube"]["description"] != m["texts"]["tiktok"]["caption"]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "4", "-i", str(out / "short.mp4"),
                    "-frames:v", "1", str(out / "preview.png")], check=True)
    approvals = work / "approvals"
    batch = make_batch(shorts, approvals)
    # Selbst bei Freigabe muss das synthetische Video blockiert bleiben:
    data = json.loads(batch.read_text(encoding="utf-8"))
    for item in data["items"]:
        item["youtube"]["approved"] = item["tiktok"]["approved"] = True
    write_json(batch, data)
    for target in ("youtube", "tiktok"):
        res = publish(target, shorts, approvals, work / "logs", cfg, live=False)
        assert res and all(r["blocked"] for r in res), res
        assert all("synthetisch" in r["blocked"] for r in res)
    print(f"Selbsttest OK: {out/'short.mp4'} · Vorschau {out/'preview.png'} · nichts hochgeladen.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="vo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--data", default=str(ROOT / "data"), help="Arbeitsordner für Zustand und Ausgaben")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("radar")
    mk = sub.add_parser("make"); mk.add_argument("brief")
    sub.add_parser("batch")
    sub.add_parser("tiktok-revoke-old", help="Alten gespeicherten TikTok-Zugang widerrufen")
    sub.add_parser("tiktok-check", help="TikTok-Anmeldung echt prüfen, ohne Upload")
    pb = sub.add_parser("publish"); pb.add_argument("target", choices=["youtube", "tiktok"])
    pb.add_argument("--live", action="store_true", help="Wirklich veröffentlichen (nur freigegebene)")
    st = sub.add_parser("selftest"); st.add_argument("--out", default="selftest-out")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    data = Path(a.data)
    if a.cmd == "radar":
        from .twitch import run_radar
        rep = run_radar(cfg, data / "state" / "radar_state.json", data / "radar")
        print(f"Radar: {rep['raw_found']} Treffer, {rep['after_dedupe']} nach Dedupe, Top {len(rep['top'])}.")
    elif a.cmd == "make":
        cmd_make(Path(a.brief), cfg, data / "shorts")
    elif a.cmd == "batch":
        print(f"Freigabe-Batch: {make_batch(data / 'shorts', data / 'approvals')}")
    elif a.cmd == "publish":
        res = publish(a.target, data / "shorts", data / "approvals", data / "logs", cfg, live=a.live)
        for r in res:
            print(f"[{r['mode']}] {r['target']} {r['short_id']}: {r['blocked'] or 'würde veröffentlicht' if r['mode']=='dry-run' else r.get('result') or r['blocked']}")
        if not res:
            print("Keine Shorts vorhanden.")
    elif a.cmd == "tiktok-revoke-old":
        from .publish import tiktok_revoke_stored
        print(tiktok_revoke_stored())
    elif a.cmd == "tiktok-check":
        from .publish import tiktok_check
        r = tiktok_check()
        print(f"OK Token-Erneuerung. Berechtigungen: {r['scope']}")
        print(f"OK user.info.basic – Anzeigename: {r['display_name']}")
        print(f"OK Posting-Abfrage (kein Upload) – Creator: @{r['creator_username']}, "
              f"Sichtbarkeiten: {r['privacy_level_options']}")
        if r["refresh_token_rotated"]:
            print("ACHTUNG: TikTok hat einen NEUEN Refresh-Token ausgegeben. Bitte das Mac-Skript "
                  "erneut ausführen und TIKTOK_REFRESH_TOKEN ersetzen.")
            return 3
        print("OK Refresh-Token unverändert – GitHub-Secret bleibt gültig.")
    elif a.cmd == "selftest":
        selftest(cfg, Path(a.out).resolve())


if __name__ == "__main__":
    sys.exit(main())
