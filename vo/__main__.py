"""Kommandozeile:

  python -m vo radar                       Twitch-Radar (braucht TWITCH_CLIENT_ID/SECRET)
  python -m vo radar-clips                 Radar → Download → Short → Dry-Run (nie Upload)
  python -m vo autopilot --watch           Lokal stündlich vorbereiten, ohne Upload
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

from .common import ROOT, load_config, write_json
from .pipeline import make_short
from .publish import make_batch, publish
from .radar_clips import DEFAULT_LIMIT, MAX_LIMIT, prepare_clips


def cmd_make(brief_path: Path, cfg: dict, shorts_root: Path) -> Path:
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    short_id = brief.get("id") or re.sub(r"[^a-z0-9]+", "-", brief_path.stem.lower())
    out = make_short(brief, cfg, shorts_root, brief_path.parent, short_id)
    print(f"Short fertig: {out/'short.mp4'}")
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
    extra = float(cfg["render"].get("outro_seconds", 0) or 0)  # Abspann kommt zum 6-s-Schnitt dazu
    assert 5.5 <= v["duration"] <= 6.5 + extra, v
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
    auto = sub.add_parser("radar-clips", help="Radar-Treffer schneiden, ohne Upload")
    auto.add_argument("--limit", type=int, choices=range(1, MAX_LIMIT + 1), default=DEFAULT_LIMIT)
    from .clip_insights import MODELS
    pilot = sub.add_parser("autopilot", help="Lokal schneiden, MP4 analysieren und optional zu YouTube hochladen")
    pilot.add_argument("--watch", action="store_true", help="Stündlich erneut prüfen (höchstens ein Upload pro Stunde)")
    pilot.add_argument("--youtube", choices=("off", "private", "unlisted", "public"), default="off")
    pilot.add_argument("--tiktok-inbox", action="store_true", help="Entwürfe über TikToks offizielle Inbox-API senden")
    pilot.add_argument("--text-source", choices=("ollama", "files"), default="ollama",
                       help="files nutzt die TXT-Dateien zum Clip und braucht kein Ollama")
    pilot.add_argument("--model", choices=MODELS, default=MODELS[0])
    pilot.add_argument("--max-uploads", type=int, choices=range(1, 6), default=1,
                       help="Höchstens so viele Shorts pro Durchgang (1-5)")
    pilot.add_argument("--min-gap-minutes", type=int, default=60,
                       help="Mindestabstand zum letzten Upload-Versuch in Minuten")
    pilot.add_argument("--env-file", type=Path, help="Lokale KEY=VALUE-Datei, niemals ins Repo committen")
    mk = sub.add_parser("make"); mk.add_argument("brief")
    sub.add_parser("batch")
    sub.add_parser("tiktok-revoke-old", help="Alten gespeicherten TikTok-Zugang widerrufen")
    sub.add_parser("tiktok-check", help="TikTok-Anmeldung echt prüfen, ohne Upload")
    sub.add_parser("youtube-check", help="YouTube-Zugang und Zielkanal prüfen, ohne Upload")
    ex = sub.add_parser("export", help="Übrige GTA-Clips für manuelles TikTok-Posten exportieren")
    ex.add_argument("--out", type=Path, default=Path("tiktok-export"))
    ex.add_argument("--limit", type=int, default=15)
    ex.add_argument("--per-streamer", type=int, default=2, help="Höchstens so viele Clips pro Streamer")
    ex.add_argument("--all-recent", action="store_true",
                    help="Alle GTA-Clips der letzten 7 Tage berücksichtigen, nicht nur die mit neuem Aufrufzuwachs")
    ex.add_argument("--all-time", action="store_true", help="Meistgesehene Clips aller Zeiten statt nur 7 Tage")
    ex.add_argument("--redo", default="", help="Komma-getrennte Twitch-Clip-Slugs gezielt neu exportieren")
    ex.add_argument("--any-game", action="store_true",
                    help="Auch Clips aus anderen Spielen (Prio 2, Enis 2026-11-25), nicht nur GTA")
    ex.add_argument("--logins", default="", help="Nur diese Streamer (Komma-getrennt, aus der Allowlist)")
    vm = sub.add_parser("vod-mine", help="Laute Momente aus GTA-VODs der Allowlist als Rohmaterial holen")
    vm.add_argument("--out", type=Path, default=Path("vod-momente"))
    vm.add_argument("--per-vod", type=int, default=4)
    vm.add_argument("--vods", type=int, default=1, help="VODs pro Streamer (neueste zuerst)")
    vm.add_argument("--logins", default="", help="Komma-getrennte Twitch-Logins (leer = alle)")
    cp = sub.add_parser("compose", help="Format v3 aus Rohmaterial (_roh/source.mp4 + words.json) und edit.json bauen")
    cp.add_argument("folder", type=Path)
    pb = sub.add_parser("publish"); pb.add_argument("target", choices=["youtube", "tiktok"])
    pb.add_argument("--live", action="store_true", help="Wirklich veröffentlichen (nur freigegebene)")
    st = sub.add_parser("selftest"); st.add_argument("--out", default="selftest-out")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    data = Path(a.data)
    if a.cmd in {"radar", "radar-clips"}:
        from .twitch import run_radar
        try:
            rep = run_radar(cfg, data / "state" / "radar_state.json", data / "radar")
        except (OSError, RuntimeError, KeyError):
            raise SystemExit("Radar konnte nicht laufen. API-Zugriff und Konfiguration prüfen.") from None
        print(f"Radar: {rep['raw_found']} Treffer, {rep['after_dedupe']} nach Dedupe, Top {len(rep['top'])}.")
        if a.cmd == "radar-clips":
            result = prepare_clips(rep, cfg, data, limit=a.limit)
            print(f"Schnitt: {len(result['rendered'])} fertig, {len(result['skipped'])} übersprungen, "
                  f"{len(result['failed'])} fehlgeschlagen. Kein Upload.")
            return 1 if result["failed"] and not result["rendered"] else None
    elif a.cmd == "autopilot":
        from .autopilot import load_local_env, run
        try:
            if a.env_file:
                load_local_env(a.env_file)
            return run(cfg, data, mode=a.youtube, model=a.model, watch=a.watch,
                       tiktok_inbox=a.tiktok_inbox, text_source=a.text_source,
                       max_uploads=a.max_uploads, min_gap_minutes=max(0, a.min_gap_minutes))
        except (OSError, ValueError, RuntimeError) as exc:
            # Netzfehler werden schon in run_cycle abgefangen. Keine OAuth-Antworten loggen.
            raise SystemExit(str(exc)) from None
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
    elif a.cmd == "export":
        from .export import run_export
        if a.all_recent:
            cfg = {**cfg, "radar": {**cfg["radar"], "min_view_delta": 0, "top_n": 200}}
        if a.all_time:
            cfg = {**cfg, "radar": {**cfg["radar"], "min_view_delta": 0, "top_n": 400, "all_time": True, "all_time_days": 365}}
        only = {x.strip().lower() for x in a.logins.split(",") if x.strip()}
        if only:
            al = cfg["clip_allowlist"]
            cfg = {**cfg, "clip_allowlist": {**al, "streamers": [
                {**s, "active": s.get("active", True) and s["twitch_login"].lower() in only} for s in al["streamers"]]}}
        if a.any_game:
            cfg = {**cfg, "gta_filter": {**cfg.get("gta_filter", {}), "enabled": False}}
        rows = run_export(cfg, data.resolve() / "autopilot", a.out, limit=max(1, min(a.limit, 40)),
                          per_streamer=max(1, min(a.per_streamer, 5)), any_game=a.any_game,
                          redo=frozenset(x.strip() for x in a.redo.split(",") if x.strip()))
        print(f"Export: {len(rows)} Clips in {a.out}")
        notes = a.out / "CAPTIONS.md"
        if notes.is_file() and "Zurückgehalten" in notes.read_text(encoding="utf-8"):
            print(notes.read_text(encoding="utf-8").split("# Zurückgehalten", 1)[1])
        return 0
    elif a.cmd == "vod-mine":
        from .vod_mine import mine
        rows = mine(cfg, data.resolve() / "autopilot", a.out, per_vod=max(1, min(a.per_vod, 8)),
                    vods_per_streamer=max(1, min(a.vods, 3)),
                    logins=[x.strip().lower() for x in a.logins.split(",") if x.strip()] or None)
        print(f"VOD-Momente: {len(rows)} in {a.out}")
    elif a.cmd == "compose":
        from .compose import compose
        print(compose(a.folder, cfg))
    elif a.cmd == "youtube-check":
        from .youtube_check import check
        return check(cfg["youtube_channel"])
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
