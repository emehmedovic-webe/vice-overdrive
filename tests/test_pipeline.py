"""Offline-Tests (kein Netzwerk, keine Secrets)."""
import base64
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vo import allowlist  # noqa: E402
from vo.autopilot import prune_mp4, run_cycle, tiktok_local_token  # noqa: E402
from vo.clip_game import clip_game, hashtags, youtube_game  # noqa: E402
from vo.clip_insights import NoVisualEvidence, describe  # noqa: E402
from vo.common import load_config, write_json  # noqa: E402
import vo.publish as pub  # noqa: E402
from vo.publish import blocked_reason, make_batch, publish, tiktok_init_body, youtube_body  # noqa: E402
from vo.radar_clips import ClipError, download_clip, prepare_clips, source_for  # noqa: E402
from vo.render import RightsError, check_rights, probe  # noqa: E402
from vo.texts import build_texts  # noqa: E402
from vo.twitch import Helix, dedupe, run_radar  # noqa: E402
from vo.youtube_radar import YouTubeReader, is_gta  # noqa: E402

CFG = load_config()
GTA6_ONLY = copy.deepcopy(CFG)
# Bestehende Tests decken beide Spiele ab; der Live-Filter steht in config.json (nur GTA VI).
CFG["gta_filter"]["categories"] = ["Grand Theft Auto V", "Grand Theft Auto VI"]
CFG["gta_filter"]["games"] = ["gta5", "gta6"]
for _s in CFG["clip_allowlist"]["streamers"]:
    _s["active"] = True  # Live sind xQc/Speed pausiert (nur deutsche Streamer); Tests prüfen alle Pfade.
CFG["tiktok"]["mode"] = "inbox"  # Produktiver Autopilot arbeitet nur mit Inbox-Entwürfen.
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def clip(cid, bid, views, *, video="v1", offset=100, title="Krasser Moment", lang="de", hours_ago=2,
         game="32982"):
    return {"id": cid, "url": f"https://clips.twitch.tv/{cid}", "broadcaster_id": bid,
            "broadcaster_name": f"user{bid}", "title": title, "language": lang, "view_count": views,
            "video_id": video, "vod_offset": offset, "duration": 30.0, "game_id": game,
            "created_at": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")}


GAMES = {"Grand Theft Auto V": "32982", "Grand Theft Auto VI": "1234567"}


class FakeTwitch:
    """Simuliert Helix-Antworten. views wird zwischen zwei Läufen angepasst."""

    def __init__(self, unknown=()):
        self.calls = []
        self.unknown = set(unknown)
        self.views = {"a": 1000, "b": 400, "c": 900, "d": 50}

    def __call__(self, method, url, headers=None, params=None, form=None, body=None, timeout=30):
        self.calls.append((method, url, params))
        if "oauth2/token" in url:
            return {"access_token": "fake"}
        if url.endswith("/users"):
            return {"data": [{"id": str(i), "login": l} for i, (_, l) in enumerate(params, 1)
                             if l not in self.unknown]}
        if url.endswith("/games"):
            return {"data": [{"id": GAMES[n], "name": n} for _, n in params if n in GAMES]}
        if url.endswith("/clips"):
            v = self.views
            if params.get("broadcaster_id") == "1":
                return {"data": [clip("a", "1", v["a"]), clip("a2", "1", v["a"] - 10, offset=110),
                                 clip("chat", "1", 99999, video="v5", game="509658"),
                                 clip("foreign", "999", 99999, video="v6")]}  # Just Chatting
            if params.get("broadcaster_id") == "2":
                return {"data": [clip("b", "2", v["b"], video="v2", game="1234567"),
                                 clip("d", "2", v["d"], video="v8")]}
            if params.get("broadcaster_id") in ("4", "5"):
                return {"data": []}
            if params.get("broadcaster_id") == "3":
                return {"data": [clip("c", "3", v["c"], video="v7", lang="en")]}
            return {"data": []}
        raise AssertionError(url)


class RadarTests(unittest.TestCase):
    def test_live_allowlist_is_german_only(self):
        from vo import allowlist
        active = {s["twitch_login"] for s in allowlist.streamers(GTA6_ONLY)}
        self.assertEqual(active, {"montanablack88", "eligella", "xrohat", "trymacs"})

    def test_dedupe_merges_same_vod_window_and_same_id(self):
        groups = dedupe([clip("x", "1", 10), clip("y", "1", 20, offset=115), clip("z", "1", 5, offset=500, title="anders"),
                         {**clip("x", "1", 10), "found_via": ["allowlist:x"]}])
        ids = {g["id"]: g for g in groups}
        self.assertEqual(set(ids), {"y", "z"})
        self.assertIn("x", ids["y"]["duplicates"])

    def test_radar_only_allowlist_and_gta(self):
        fake = FakeTwitch()
        client = Helix("id", "secret", fetch=fake)
        with tempfile.TemporaryDirectory() as tmp:
            state, out = Path(tmp) / "state.json", Path(tmp) / "radar"
            r1 = run_radar(CFG, state, out, client=client, now=NOW)
            ids1 = [c["id"] for c in r1["top"]]
            self.assertNotIn("foreign", ids1)            # widersprüchliche Kanal-ID
            self.assertNotIn("chat", ids1)               # kein GTA → verworfen
            self.assertEqual(r1["skipped_not_gta"], 1)
            self.assertIn("c", ids1)                     # englischer Clip zählt (US-Streamer)
            self.assertIn("b", ids1)                     # GTA VI zählt
            self.assertNotIn("a2", ids1)                 # Duplikat zusammengefasst
            self.assertEqual(ids1[0], "a")
            self.assertEqual(r1["top"][0]["streamer_login"], "montanablack88")
            self.assertEqual(r1["missing_logins"], [])
            # Zweiter Check: c wächst stark, a kaum → c muss vorn liegen
            fake.views.update({"a": 1010, "c": 1900, "b": 450, "d": 50})
            r2 = run_radar(CFG, state, out, client=client, now=NOW + timedelta(hours=1))
            self.assertEqual([c["id"] for c in r2["top"]][:3], ["c", "b", "a"])
            self.assertEqual(r2["top"][0]["view_delta"], 1000)
            self.assertNotIn("d", [c["id"] for c in r2["top"]])  # kein Zuwachs
            self.assertTrue(list(out.glob("radar-*.md")))
            logins = [p for m, u, p in fake.calls if u.endswith("/users")][0]
            self.assertEqual([l for _, l in logins], allowlist.logins(CFG))
            # Es wird nie kanalübergreifend in einer Kategorie gesucht:
            self.assertFalse([p for m, u, p in fake.calls if u.endswith("/clips") and "game_id" in p])

    def test_radar_reports_unknown_login(self):
        fake = FakeTwitch(unknown={"xrohat"})
        with tempfile.TemporaryDirectory() as tmp:
            r = run_radar(CFG, Path(tmp) / "s.json", Path(tmp) / "r", client=Helix("i", "s", fetch=fake), now=NOW)
            self.assertEqual(r["missing_logins"], ["xrohat"])
            self.assertIn("nicht gefunden: xrohat", next(Path(tmp, "r").glob("*.md")).read_text())

    def test_youtube_videos_join_ranking_read_only(self):
        calls = []

        def fake_yt(method, url, headers=None, params=None, **kw):
            calls.append((method, url, params))
            self.assertEqual(method, "GET")                      # nur lesen
            self.assertEqual(params.get("key"), "k")
            if url.endswith("/channels"):
                if params["forHandle"] == "@xQc":
                    return {"items": []}                         # Handle unbekannt
                return {"items": [{"id": "UC" + params["forHandle"][1:],
                                   "contentDetails": {"relatedPlaylists": {"uploads": "UU" + params["forHandle"][1:]}}}]}
            if url.endswith("/playlistItems"):
                return {"items": [{"contentDetails": {"videoId": params["playlistId"] + n}} for n in ("1", "2", "3", "4", "5")]}
            if url.endswith("/videos"):
                out = []
                for vid in params["id"].split(","):
                    title = {"1": "GTA 6 RP Chaos", "2": "Minecraft Stream", "3": "Grand Theft Auto alt",
                             "4": "GTA falscher Kanal", "5": "GTA Livestream"}[vid[-1]]
                    hours = 400 if vid.endswith("3") else 3
                    out.append({"id": vid, "snippet": {"title": title, "description": "", "channelTitle": vid[2:-1],
                                "channelId": "UCother" if vid.endswith("4") else "UC" + vid[2:-1],
                                "liveBroadcastContent": "live" if vid.endswith("5") else "none",
                                "publishedAt": (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                                "statistics": {"viewCount": "5000" if "IShowSpeed" in vid else "300"},
                                "contentDetails": {"duration": "PT45S"}})
                return {"items": out}
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            r = run_radar(CFG, Path(tmp) / "s.json", Path(tmp) / "r", client=Helix("i", "s", fetch=FakeTwitch()),
                          now=NOW, youtube=YouTubeReader(api_key="k", fetch=fake_yt))
            yt = [c for c in r["top"] if c["platform"] == "youtube"]
            self.assertEqual({c["id"] for c in yt}, {"yt:UUIShowSpeed1", "yt:UUMontanaBlack1", "yt:UUEligella1", "yt:UUTrymacs1"})
            self.assertEqual(r["top"][0]["id"], "yt:UUIShowSpeed1")   # meiste Aufrufe vorn
            self.assertEqual(r["top"][0]["streamer_login"], "ishowspeed")
            self.assertEqual(r["youtube"]["missing_handles"], ["@xQc"])
            self.assertEqual(r["youtube"]["skipped_not_gta"], 4)       # Minecraft je Kanal
            self.assertFalse([u for _, u, _ in calls if u.endswith("/search")])  # kein teures search.list
            self.assertIn("Handle nicht gefunden: @xQc", next(Path(tmp, "r").glob("*.md")).read_text())

    def test_youtube_error_does_not_break_twitch(self):
        def broken(*a, **k):
            raise RuntimeError("HTTP 403 bei GET channels")
        with tempfile.TemporaryDirectory() as tmp:
            r = run_radar(CFG, Path(tmp) / "s.json", Path(tmp) / "r", client=Helix("i", "s", fetch=FakeTwitch()),
                          now=NOW, youtube=YouTubeReader(api_key="k", fetch=broken))
            self.assertTrue(r["top"])
            self.assertIn("FEHLER", r["youtube"]["status"])

    def test_gta_detection(self):
        self.assertTrue(is_gta({"snippet": {"title": "Monte in GTA RP"}}))
        self.assertTrue(is_gta({"snippet": {"title": "x", "tags": ["Grand Theft Auto VI"]}}))
        self.assertFalse(is_gta({"snippet": {"title": "Fortnite mit Freunden"}}))

    def test_inactive_streamer_not_searched(self):
        cfg = copy.deepcopy(CFG)
        cfg["clip_allowlist"]["streamers"].append({"twitch_login": "nurvorgemerkt", "name": "X", "active": False})
        self.assertNotIn("nurvorgemerkt", allowlist.logins(cfg))


class RadarClipTests(unittest.TestCase):
    @staticmethod
    def _twitch(slug="EpicClip", login="montanablack88"):
        return {"id": slug, "platform": "twitch", "streamer_login": login,
                "url": f"https://clips.twitch.tv/{slug}", "title": "GTA <RP> am Strand"}

    @staticmethod
    def _youtube():
        return {"id": "yt:AbCd0123_-x", "platform": "youtube", "streamer_login": "ishowspeed",
                "url": "https://www.youtube.com/watch?v=AbCd0123_-x", "title": "GTA bei Speed"}

    def test_download_gate_blocks_inactive_missing_proof_and_wrong_urls(self):
        cfg = copy.deepcopy(CFG)
        first = cfg["clip_allowlist"]["streamers"][0]
        first["proof"] = " "
        top = [self._twitch(), self._twitch(login="fremderkanal"), self._youtube(),
               {**self._twitch(login="eligella"), "url": "https://clips.twitch.tv@other.example/EpicClip"},
               {**self._twitch(login="eligella"), "url": "https://clips.twitch.tv/AndererClip"},
               {**self._twitch(login="eligella"), "url": "https://www.twitch.tv/xrohat/clip/EpicClip"},
               self._twitch(login="xrohat")]
        cfg["clip_allowlist"]["streamers"][2]["active"] = False
        with tempfile.TemporaryDirectory() as tmp, patch("subprocess.run") as proc:
            result = prepare_clips({"top": top}, cfg, Path(tmp))
            self.assertEqual(result["rendered"], [])
            self.assertEqual(len(result["skipped"]), len(top))
            self.assertIn("Plattform-Downloadfreigabe", result["skipped"][2]["reason"])
            proc.assert_not_called()

    def test_youtube_approval_and_canonical_url(self):
        cfg = copy.deepcopy(CFG)
        next(e for e in cfg["clip_allowlist"]["streamers"] if e["twitch_login"] == "ishowspeed")["youtube_download_proof"] = "Testbeleg – keine echte Freigabe"
        item = {**self._youtube(), "url": "https://youtu.be/AbCd0123_-x?list=ignored"}
        sid, url, streamer = source_for(item, cfg)
        self.assertEqual((sid, url, streamer),
                         ("youtube-AbCd0123_-x", self._youtube()["url"], "ishowspeed"))
        with self.assertRaisesRegex(ClipError, "Radar-ID"):
            source_for({**item, "url": "https://youtu.be/mismatch123"}, cfg)

    def test_downloader_builds_bounded_command_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"YT_API_KEY": "test-only"}):
            stage = Path(tmp)

            def fake_process(cmd, **kwargs):
                self.assertNotIn("YT_API_KEY", kwargs["env"])
                self.assertEqual(kwargs["cwd"], stage)
                self.assertEqual(kwargs["timeout"], 120)
                self.assertTrue(kwargs["check"])
                self.assertEqual(cmd[-2:], ["--", self._youtube()["url"]])
                self.assertIn("--no-playlist", cmd)
                self.assertIn("*0-59", cmd)
                (stage / "source.webm").write_bytes(b"test")

            with patch("vo.radar_clips.subprocess.run", side_effect=fake_process):
                self.assertEqual(download_clip(self._youtube()["url"], "youtube", stage, 59).name, "source.webm")

    def test_attempt_budget_and_failure_without_source_residue(self):
        cfg = copy.deepcopy(CFG)
        cfg["render"]["max_seconds"] = 999
        calls = []

        def broken(url, platform, stage, seconds):
            self.assertEqual(seconds, 59)
            (stage / "source.mp4.part").touch()
            calls.append(url)
            raise ClipError("Test: Clip nicht verfügbar.")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {"top": [self._twitch("A"), self._twitch("A"), self._twitch("B"), self._twitch("C")]}
            result = prepare_clips(report, cfg, root, limit=2, download=broken)
            self.assertEqual(calls, ["https://clips.twitch.tv/A", "https://clips.twitch.tv/B"])
            self.assertEqual([x["short_id"] for x in result["failed"]], ["twitch-A", "twitch-B"])
            self.assertFalse(list((root / "shorts").iterdir()))
            self.assertFalse((root / "approvals").exists())

    def test_unknown_tiktok_mode_is_rejected_before_download(self):
        cfg = {**CFG, "tiktok": {**CFG["tiktok"], "mode": "public-now"}}
        with tempfile.TemporaryDirectory() as tmp, patch("subprocess.run") as proc:
            with self.assertRaisesRegex(ValueError, "TikTok-Modus"):
                prepare_clips({"top": [self._twitch()]}, cfg, Path(tmp))
            proc.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe fehlen")
    def test_radar_clips_render_and_hand_off_offline(self):
        cfg = copy.deepcopy(CFG)
        cfg["render"].update(width=720, height=1280, max_seconds=1)
        next(e for e in cfg["clip_allowlist"]["streamers"] if e["twitch_login"] == "ishowspeed")["youtube_download_proof"] = "Nur Test"
        report = {"top": [self._twitch(), self._youtube()]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "synthetic.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=15",
                "-t", "2", "-c:v", "libx264", str(source),
            ], check=True)
            urls = []

            def fake_download(url, platform, stage, seconds):
                self.assertEqual(seconds, 1)
                urls.append(url)
                return Path(shutil.copyfile(source, stage / "source.mp4"))

            with patch("urllib.request.urlopen", side_effect=AssertionError("Kein Netzwerk im Test")):
                result = prepare_clips(report, cfg, root, download=fake_download)
                self.assertEqual(urls, [self._twitch()["url"], self._youtube()["url"]])
                self.assertEqual(result["rendered"], ["twitch-EpicClip", "youtube-AbCd0123_-x"])
                self.assertEqual(result["failed"], [])
                for sid, name, url in [
                    ("twitch-EpicClip", "MontanaBlack", "https://www.twitch.tv/montanablack88"),
                    ("youtube-AbCd0123_-x", "IShowSpeed", "https://www.youtube.com/@IShowSpeed"),
                ]:
                    out = root / "shorts" / sid
                    info = probe(out / "short.mp4")
                    self.assertEqual((info["width"], info["height"], info["video_codec"], info["audio_codec"]),
                                     (1080, 1920, "h264", "aac"))
                    self.assertLessEqual(info["duration"], 1.1)
                    for platform in ("youtube", "tiktok"):
                        body = (out / f"{platform}.txt").read_text()
                        self.assertIn(name, body)
                        self.assertIn(url, body)
                    manifest = json.loads((out / "manifest.json").read_text())
                    self.assertEqual(manifest["rights"]["type"], "clipper_program")
                    self.assertEqual(manifest["published"], {})
                batch = json.loads(next((root / "approvals").glob("batch-*.json")).read_text())
                self.assertTrue(all(not row[platform]["approved"] for row in batch["items"]
                                    for platform in ("youtube", "tiktok")))
                log = json.loads(next((root / "logs").glob("publish-tiktok-dryrun-*.json")).read_text())
                self.assertTrue(all(row["blocked"] == "nicht freigegeben" for row in log))
                self.assertTrue(all("/inbox/" in row["payload"]["endpoint"] for row in log))
                yt_log = json.loads(next((root / "logs").glob("publish-youtube-dryrun-*.json")).read_text())
                self.assertEqual(len(yt_log), 2)
                for row in yt_log:
                    self.assertEqual(row["blocked"], "nicht freigegeben")
                    self.assertEqual(row["mode"], "dry-run")
                    self.assertTrue(row["payload"]["snippet"]["title"].endswith("#Shorts"))
                    self.assertEqual(row["payload"]["status"]["privacyStatus"], "private")
                self.assertFalse(list(root.rglob("source.mp4")))
                second = prepare_clips(report, cfg, root, download=fake_download)
                self.assertEqual(second["rendered"], [])
                self.assertEqual(len(urls), 2)


class AutopilotTests(unittest.TestCase):
    def _item(self, cid="race-a", *, video="v123", offset=100):
        return {**clip(cid, "1", 100, video=video, offset=offset),
                "title": "Neue Szene", "platform": "twitch", "streamer_login": "montanablack88"}

    def _cycle(self, root, item, **kw):
        def fake_render(report, cfg, data, *, limit, handoff):
            self.assertEqual(limit, 1)
            self.assertFalse(handoff)
            row = report["top"][0]
            sid = "twitch-" + row["id"]
            out = data / "shorts" / sid
            write_json(out / "manifest.json", {"short_id": sid, "source": row["url"],
                      "file": "short.mp4", "streamer": "montanablack88",
                      "rights": {"type": "clipper_program", "proof": "Test"}, "published": {}})
            (out / "short.mp4").write_bytes(b"test")
            return {"rendered": [sid]}

        def fake_analyze(path, duration, game, model):
            self.assertEqual(game, "gta5")
            self.assertEqual(path.name, "short.mp4")
            return {"scene": "pursuit", "evidence_frames": [2, 4],
                    "headline": "Die Abkürzung zwischen zwei Streifenwagen",
                    "observation": "Ein roter Wagen zieht zwischen zwei Streifenwagen hindurch.",
                    "question": "Wärt ihr an der Stelle links abgebogen?"}

        defaults = {"mode": "off", "clock": lambda: NOW, "render": fake_render, "analyze": fake_analyze,
                    "token": lambda: self.fail("Ohne Live-Modus keine Anmeldung"),
                    "upload": lambda *a: self.fail("Kein echter Upload im Test")}
        items = kw.pop("items", None) or [item]
        defaults.update(kw)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": ""}), patch("vo.autopilot.probe", return_value={
            "width": 1080, "height": 1920, "video_codec": "h264", "duration": 23,
        }):
            return run_cycle(CFG, root, radar=lambda *a: {"top": items, "gta_categories": GAMES},
                             **defaults)

    def test_distinguishes_games_and_conflicting_labels(self):
        self.assertEqual(clip_game(self._item(), GAMES), "gta5")
        self.assertIsNone(clip_game({**self._item(), "title": "GTA 6 Trailer"}, GAMES))
        self.assertEqual(youtube_game({"title": "Grand Theft Auto VI Trailer"}), "gta6")
        self.assertIsNone(youtube_game({"title": "GTA VI oder GTA 5?"}))
        self.assertNotIn("#GTA6", hashtags("gta5", "pursuit", "youtube"))
        self.assertIn("#Verfolgungsjagd", hashtags("gta5", "pursuit", "youtube"))
        self.assertNotIn("#GTARP", hashtags("gta6", "roleplay", "tiktok"))

    def test_prepares_only_clip_specific_description_and_correct_hashtags(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            result = self._cycle(data, self._item())
            self.assertEqual(result["status"], "prepared")
            out = data / "shorts" / result["short_id"]
            youtube = (out / "youtube.txt").read_text(encoding="utf-8")
            tiktok = (out / "tiktok.txt").read_text(encoding="utf-8")
            for text in (youtube, tiktok):
                self.assertIn("roter Wagen", text)
                self.assertIn("MontanaBlack", text)
                self.assertIn("https://www.twitch.tv/montanablack88", text)
                self.assertIn("#GTAV", text)
                self.assertNotIn("#GTA6", text)
            # Szenen-Tag passt nur noch bei YouTube; TikTok hat 2 freie Plätze neben #fyp #fy #viral.
            self.assertIn("#Verfolgungsjagd", youtube)
            self.assertIn("#Shorts", youtube)
            self.assertNotIn("#Shorts", tiktok)

    def test_does_not_use_a_repeated_description_for_another_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            self.assertEqual(self._cycle(data, self._item())["status"], "prepared")
            self.assertEqual(self._cycle(data, self._item("race-b", video="v456"))["status"], "no_suitable_clip")

    def _stage_txt_short(self, data):
        out = data / "shorts" / "twitch-race-a"
        write_json(out / "manifest.json", {"short_id": out.name, "source": self._item()["url"],
                   "file": "short.mp4", "streamer": "montanablack88",
                   "rights": {"type": "clipper_program", "proof": "Test"}, "published": {}})
        (out / "short.mp4").write_bytes(b"test")
        texts = build_texts({"streamer": "montanablack88", "game": "gta5",
                             "title": "Fast am Ziel", "hook": "Ein Clip",
                             "description": "Kurz vor dem Ziel kippt der Wagen um.",
                             "caption": "Wer hat den Wagen noch kommen sehen?"}, CFG)
        yt = texts["youtube"]
        (out / "youtube.txt").write_text(f"{yt['title']}\n\n{yt['description']}\n", encoding="utf-8")
        (out / "tiktok.txt").write_text(texts["tiktok"]["caption"] + "\n", encoding="utf-8")
        return out, texts

    def test_file_mode_prepares_exact_texts_without_ollama_or_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            out, expected = self._stage_txt_short(data)
            result = self._cycle(data, self._item(), text_source="files",
                                 analyze=lambda *a: self.fail("Dateimodus darf nicht Ollama aufrufen"))
            self.assertEqual(result["status"], "prepared")
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["texts"]["youtube"], expected["youtube"])
            self.assertEqual(manifest["texts"]["tiktok"], expected["tiktok"])
            self.assertEqual(manifest["autopilot"]["text_source"], "files")
            self.assertEqual(manifest["published"], {})

    def test_file_mode_passes_exact_title_and_description_to_youtube(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            out, expected = self._stage_txt_short(data)

            def fake_upload(video, body, access):
                self.assertEqual(video, out / "short.mp4")
                self.assertEqual(body["snippet"]["title"], expected["youtube"]["title"])
                self.assertEqual(body["snippet"]["description"], expected["youtube"]["description"])
                return "fake-file-mode-id"

            result = self._cycle(data, self._item(), text_source="files", mode="private",
                                 analyze=lambda *a: self.fail("Kein Ollama"),
                                 token=lambda: "fake", channel=lambda *a: True, upload=fake_upload)
            self.assertEqual(result["status"], "youtube_sent")

    def test_batch_uploads_several_distinct_clips_per_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            items = [self._item("race-a", video="v1"), self._item("race-b", video="v2"),
                     self._item("race-c", video="v3")]
            def analyze(path, duration, game, model):
                return {"scene": "pursuit", "evidence_frames": [2, 4],
                        "headline": "Die Abkürzung zwischen zwei Streifenwagen",
                        "observation": f"Szene {path.parent.name}: ein Wagen zieht vorbei.",
                        "question": "Wärt ihr an der Stelle links abgebogen?"}

            result = self._cycle(Path(tmp), None, items=items, mode="private", max_uploads=2,
                                 analyze=analyze,
                                 token=lambda: "fake", channel=lambda *a: True,
                                 upload=lambda v, b, a: sent.append(v.parent.name) or f"id-{len(sent)}")
            self.assertEqual(result["status"], "batch")
            self.assertEqual(result["youtube_sent"], 2)
            self.assertEqual(len(sent), 2)

    def test_gta6_only_config_skips_gta5_clips(self):
        self.assertEqual(GTA6_ONLY["gta_filter"]["games"], ["gta6"])
        with tempfile.TemporaryDirectory() as tmp, \
                patch("vo.autopilot.probe", return_value={"width": 1080, "height": 1920,
                                                          "video_codec": "h264", "duration": 23}), \
                patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
            result = run_cycle(GTA6_ONLY, Path(tmp), radar=lambda *a: {"top": [self._item()], "gta_categories": GAMES},
                               render=lambda *a, **k: self.fail("GTA V darf nicht geschnitten werden"),
                               clock=lambda: NOW)
        self.assertEqual(result["status"], "no_suitable_clip")

    def test_blocked_titles_are_never_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = {**self._item(), "title": "18+ GTA 6 First Nude Showering Scene"}
            cfg = {**CFG, "gta_filter": {**CFG["gta_filter"], "title_blocklist": ["nude"]}}
            with patch("vo.autopilot.probe"), patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
                result = run_cycle(cfg, Path(tmp), radar=lambda *a: {"top": [item], "gta_categories": GAMES},
                                   render=lambda *a, **k: self.fail("darf nicht geschnitten werden"),
                                   clock=lambda: NOW)
        self.assertEqual(result["status"], "no_suitable_clip")

    def test_export_skips_sent_drafts_and_blocks_later_tiktok(self):
        from vo.export import run_export
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autopilot"
            write_json(root / "state" / "autopilot.json", {"last_attempt": None, "clips": {
                "twitch-race-a": {"tiktok_status": "sent", "source_ids": ["race-a"], "video_id": "v1",
                                  "vod_offset": 100}}})

            def render(report, cfg, data, *, limit, handoff):
                row = report["top"][0]
                out = data / "shorts" / ("twitch-" + row["id"])
                out.mkdir(parents=True)
                (out / "short.mp4").write_bytes(b"mp4")
                (out / "tiktok.txt").write_text(
                    "Monte fährt Auto. Monte fährt Auto. 👀 Was hättet ihr gemacht?\n"
                    "🎥 Clip von MontanaBlack: https://www.twitch.tv/montanablack88\n#GTA6 #MontanaBlack\n",
                    encoding="utf-8")
                return {"rendered": ["twitch-" + row["id"]]}

            items = [self._item("race-a", video="v1"), self._item("race-b", video="v2")]
            rows = run_export(CFG, root, Path(tmp) / "export",
                              radar=lambda *a: {"top": items, "gta_categories": GAMES}, render=render)
            self.assertEqual(len(rows), 1)
            folder = Path(tmp) / "export" / rows[0]["file"]
            self.assertTrue((folder / "video.mp4").is_file())
            caption = (folder / "caption.txt").read_text(encoding="utf-8")
            self.assertEqual(caption, "Monte fährt Auto.\n\n#GTA6 #MontanaBlack #fyp #fy #viral\n")
            self.assertIn("twitch.tv", (Path(tmp) / "export" / "CAPTIONS.md").read_text(encoding="utf-8"))
            state = json.loads((root / "state" / "autopilot.json").read_text(encoding="utf-8"))
            self.assertEqual(state["clips"]["twitch-race-b"]["tiktok_status"], "exported")
            # Ein zweiter Export liefert denselben Clip nicht noch einmal.
            again = run_export(CFG, root, Path(tmp) / "export2",
                               radar=lambda *a: {"top": items, "gta_categories": GAMES}, render=render)
            self.assertEqual(again, [])

    def test_teaser_only_when_peak_is_late(self):
        from vo.render import teaser_window
        self.assertIsNone(teaser_window(None, 0, 30, 1.5))
        self.assertIsNone(teaser_window(2.0, 0, 30, 1.5))  # stärkster Moment ist schon vorne
        self.assertEqual(teaser_window(11.0, 0, 30, 1.5), (10.25, 1.5))
        self.assertIsNone(teaser_window(40.0, 0, 30, 1.5))  # außerhalb des Schnitts

    def test_export_mixes_streamers(self):
        from vo.export import mix_by_streamer
        top = [{"id": f"t{i}", "streamer_login": "trymacs", "view_count": 5} for i in range(4)]
        top += [{"id": "r0", "streamer_login": "xrohat", "view_count": 0},
                {"id": "r1", "streamer_login": "xrohat", "view_count": 9},
                {"id": "m0", "streamer_login": "montanablack88", "view_count": 3}]
        order = [c["id"] for c in mix_by_streamer(top)]
        self.assertEqual(order[:3], ["t0", "r1", "m0"])  # abwechselnd, Rohat-Clip mit Aufrufen zuerst
        self.assertEqual(order[3:5], ["t1", "r0"])

    def test_export_caption_is_only_description_and_hashtags(self):
        from vo.export import export_caption
        from vo.texts import tiktok_caption_problems, tiktok_description
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            brief = {"streamer": "montanablack88", "game": "gta6", "topic": "Monte fährt Auto",
                     "caption": "Monte springt in einen roten SUV und fährt durch Vice City."}
            texts = build_texts(brief, CFG)
            self.assertIn("twitch.tv", texts["tiktok"]["caption"])
            write_json(out / "manifest.json", {"texts": texts, "source": "https://www.twitch.tv/x/clip/y",
                                               "tiktok_description": tiktok_description(brief, CFG)})
            caption = export_caption(out)
            desc, tags = caption.split("\n\n")
            self.assertEqual(desc, "Monte springt in einen roten SUV und fährt durch Vice City.")
            self.assertTrue(all(t.startswith("#") for t in tags.split()))
            self.assertLessEqual(len(tags.split()), 5)
            self.assertEqual(tags.split()[-3:], ["#fyp", "#fy", "#viral"])
            self.assertEqual(tiktok_caption_problems(caption), [])
        bad = ["Text.\n\n#GTA6\nhttps://twitch.tv/x", "Text 🎥 Clip von xQc.\n\n#GTA6",
               "Text. Was hättet ihr gemacht?\n\n#GTA6", "Gleich. Gleich.\n\n#GTA6",
               "Text.\n\n#a #b #c #d #e #f", "Text.\n\n#GTA6\n\nDrei Alternativen #GTAVI",
               "Passt gut zum Clip.\n\n#GTA6", "Nur Text ohne Hashtags"]
        for caption in bad:
            with self.subTest(caption=caption):
                self.assertTrue(tiktok_caption_problems(caption))

    def test_direct_mode_only_with_self_only(self):
        cfg = {**CFG, "tiktok": {**CFG["tiktok"], "mode": "direct", "privacy_level": "PUBLIC_TO_EVERYONE"}}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
            with self.assertRaises(ValueError):
                run_cycle(cfg, Path(tmp), mode="off", tiktok_inbox=True,
                          radar=lambda *a: self.fail("kein Radar"), clock=lambda: NOW)

    def test_known_clips_override_missing_state(self):
        from vo.autopilot import load_state
        with tempfile.TemporaryDirectory() as tmp:
            known = Path(tmp) / "known.json"
            write_json(known, {"clips": {"twitch-a": {"status": "sent", "tiktok_status": "exported",
                                                      "source_ids": ["a"]}}})
            path = Path(tmp) / "state.json"
            write_json(path, {"last_attempt": None, "clips": {"twitch-a": {"status": "prepared"}}})
            state = load_state(path, known)
        self.assertEqual(state["clips"]["twitch-a"]["status"], "sent")
        self.assertEqual(state["clips"]["twitch-a"]["tiktok_status"], "exported")

    def test_direct_post_caption_has_no_source_or_question(self):
        from vo.autopilot import tiktok_post_manifest
        from vo.texts import tiktok_caption_problems
        raw = ("Monte zieht in GTA 6 mit dem Auto über den Highway und verliert fast die Kontrolle.\n"
               "👀 Was hättet ihr gemacht?\n🎥 Clip von MontanaBlack: https://www.twitch.tv/montanablack88\n"
               "#GTA6 #MontanaBlack #GTAVI @montanablack88")
        manifest = {"source": "https://www.twitch.tv/montanablack88/clip/x", "credit": "MontanaBlack",
                    "texts": {"tiktok": {"caption": raw, "hashtags": ["#GTA6", "#MontanaBlack", "#GTAVI"]}}}
        posted = tiktok_post_manifest(manifest)["texts"]["tiktok"]["caption"]
        self.assertEqual(tiktok_caption_problems(posted), [])
        self.assertNotIn("http", posted)
        self.assertNotIn("Clip von", posted)
        self.assertNotIn("hättet", posted)
        self.assertIn("Highway", posted)
        # Quelle bleibt intern im Manifest.
        self.assertIn("Clip von", manifest["texts"]["tiktok"]["caption"])

    def test_file_mode_skips_missing_or_conflicting_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            out, _ = self._stage_txt_short(data)
            caption = out / "tiktok.txt"
            original = caption.read_text(encoding="utf-8")
            caption.unlink()
            opts = {"text_source": "files", "analyze": lambda *a: self.fail("Kein Ollama")}
            self.assertEqual(self._cycle(data, self._item(), **opts)["status"], "no_suitable_clip")
            for invalid in ("Quellenangabe fehlt", original + "#GTA6"):
                caption.write_text(invalid, encoding="utf-8")
                self.assertEqual(self._cycle(data, self._item(), **opts)["status"], "no_suitable_clip")

    def test_upload_gate_recognizes_account_and_does_not_repeat_moments(self):
        sends = []

        def fake_upload(path, body, access):
            self.assertEqual(access, "fake")
            self.assertEqual(body["status"]["privacyStatus"], "public")
            self.assertIn("roter Wagen", body["snippet"]["description"])
            sends.append(path)
            return "fake-video"

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            args = {"mode": "public", "token": lambda: "fake", "upload": fake_upload}
            wrong = self._cycle(data, self._item(), channel=lambda *a: False, **args)
            self.assertEqual(wrong["status"], "youtube_wrong_channel")
            self.assertFalse(sends)
            args["channel"] = lambda tok, handle: handle == CFG["youtube_channel"]
            self.assertEqual(self._cycle(data, self._item(), **args)["status"], "youtube_sent")
            self.assertEqual(self._cycle(data, self._item("race-b", offset=110), **args)["status"], "cooldown")
            args["clock"] = lambda: NOW + timedelta(minutes=59)
            self.assertEqual(self._cycle(data, self._item("race-b", offset=110), **args)["status"], "cooldown")
            args["clock"] = lambda: NOW + timedelta(hours=1)
            self.assertEqual(self._cycle(data, self._item("race-b", offset=110), **args)["status"], "no_suitable_clip")
            self.assertEqual(len(sends), 1)

    def test_unconfirmed_upload_is_not_retried(self):
        def failed_upload(*a):
            raise TimeoutError
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            opts = {"mode": "private", "token": lambda: "fake", "channel": lambda *a: True}
            self.assertEqual(self._cycle(data, self._item(), upload=failed_upload, **opts)["status"],
                             "youtube_unconfirmed")
            self.assertEqual(self._cycle(data, self._item(), clock=lambda: NOW + timedelta(hours=3),
                                        **opts)["status"], "no_suitable_clip")

    def test_no_visual_evidence_means_no_upload(self):
        def no_evidence(*a):
            raise NoVisualEvidence("Nichts eindeutig")
        with tempfile.TemporaryDirectory() as tmp:
            result = self._cycle(Path(tmp), self._item(), mode="private", analyze=no_evidence)
            self.assertEqual(result["status"], "no_suitable_clip")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg fehlt")
    def test_description_agent_gets_five_real_jpegs_but_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "sample.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=90x160:rate=25", "-t", "1", "-c:v", "libx264", str(video)], check=True)

            def fake_local_model(payload):
                self.assertEqual(payload["model"], "qwen3-vl:4b")
                images = payload["messages"][0]["images"]
                self.assertEqual(len(images), 5)
                self.assertTrue(all(base64.b64decode(im).startswith(b"\xff\xd8") for im in images))
                self.assertNotIn("secret-test-value", json.dumps(payload))
                return {"message": {"content": json.dumps({
                    "usable": True, "scene": "stunt", "evidence_frames": [2, 3],
                    "headline": "Sprung über die Rampe", "question": "Welche Linie würdet ihr nehmen?",
                    "observation": "Ein Auto fährt über eine schmale Rampe auf ein Dach.",
                })}}

            with patch.dict(os.environ, {"YT_CLIENT_SECRET": "secret-test-value"}):
                self.assertEqual(describe(video, 1, "gta5", "qwen3-vl:4b", chat=fake_local_model)["scene"], "stunt")
            with self.assertRaises(NoVisualEvidence):
                describe(video, 1, "gta5", "qwen3-vl:4b",
                         chat=lambda _: {"message": {"content": '{"usable": false}'}})

    def test_tiktok_upload_is_optional_and_inbox_only(self):
        calls = []

        def fake_upload(video, manifest, cfg, token):
            self.assertEqual(cfg["tiktok"]["mode"], "inbox")
            self.assertEqual(token, "fake")
            self.assertIn("roter Wagen", manifest["texts"]["tiktok"]["caption"])
            calls.append(video)
            return {"publish_id": "fake", "status": "SEND_TO_USER_INBOX", "mode": "inbox"}

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            kw = {"tiktok_inbox": True, "tt_token": lambda *a: "fake", "tt_upload": fake_upload}
            result = self._cycle(data, self._item(), **kw)
            self.assertEqual(result["tiktok"]["status"], "tiktok_inbox_accepted")
            self.assertEqual(result["youtube"]["status"], "off_or_already_attempted")
            self.assertEqual(self._cycle(data, self._item(), clock=lambda: NOW + timedelta(hours=1),
                                         **kw)["status"], "no_suitable_clip")
            self.assertEqual(len(calls), 1)

    def test_tiktok_waits_for_inbox_and_rechecks_without_resending(self):
        uploads = []
        def fake_upload(video, manifest, cfg, token):
            uploads.append(video)
            return {"publish_id": "fake-id", "status": "PROCESSING_UPLOAD", "mode": "inbox"}
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            kw = {"tiktok_inbox": True, "tt_token": lambda *a: "fake", "tt_upload": fake_upload}
            first = self._cycle(data, self._item(), **kw)
            self.assertEqual(first["tiktok"]["status"], "tiktok_inbox_pending")
            self.assertTrue(next(data.glob("shorts/*/caption.txt")).read_text().endswith("#fyp #fy #viral\n"))
            with patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
                second = run_cycle(CFG, data, **kw, radar=lambda *a: self.fail("Nicht neu rendern"),
                                   tt_fetch_status=lambda pid, tok: {"status": "SEND_TO_USER_INBOX"},
                                   clock=lambda: NOW + timedelta(hours=1))
            self.assertEqual(second["status"], "tiktok_inbox_accepted")
            self.assertEqual(len(uploads), 1)

    def test_tiktok_refresh_rotation_stays_local_and_reuses_new_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "TIKTOK_CLIENT_KEY": "key", "TIKTOK_CLIENT_SECRET": "fake",
            "TIKTOK_REFRESH_TOKEN": "old", "TIKTOK_OPEN_ID": "account-id",
        }), patch("vo.autopilot.http_json", return_value={
            "access_token": "test-access", "refresh_token": "rotated",
            "open_id": "account-id", "scope": "video.upload",
        }) as ask:
            data = Path(tmp)
            self.assertEqual(tiktok_local_token(data, "@viceoverdrive"), "test-access")
            self.assertEqual(tiktok_local_token(data, "@viceoverdrive"), "test-access")
            self.assertEqual(ask.call_args_list[0].kwargs["form"]["refresh_token"], "old")
            self.assertEqual(ask.call_args_list[1].kwargs["form"]["refresh_token"], "rotated")

    def test_only_owned_autopilot_mp4s_two_hours_old_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "autopilot"
            old = (NOW - timedelta(hours=2)).timestamp()

            def mp4(short_id, stamp, rights="clipper_program"):
                out = root / "shorts" / short_id
                write_json(out / "manifest.json", {"short_id": short_id, "file": "short.mp4",
                                                 "rights": {"type": rights}})
                video = out / "short.mp4"
                video.write_bytes(b"offline test")
                os.utime(video, (stamp, stamp))
                return video

            expired = mp4("twitch-expired", old)
            recent = mp4("youtube-recent", old + 1)
            other = mp4("twitch-own", old - 10, "own")
            original = expired.parent / "original.mp4"
            original.write_bytes(b"keep")
            os.utime(original, (old - 50, old - 50))
            description = expired.parent / "youtube.txt"
            description.write_text("bleibt", encoding="utf-8")
            sibling = root.parent / "short.mp4"
            sibling.write_bytes(b"keep")
            self.assertEqual(prune_mp4(root, now=NOW), 1)
            self.assertFalse(expired.exists())
            self.assertTrue(all(p.exists() for p in (
                recent, other, description, original, sibling, expired.parent / "manifest.json",
            )))
            self.assertEqual(prune_mp4(root, now=NOW), 0)

    def test_channel_identity_check_matches_the_authorized_handle(self):
        with patch("vo.publish.http_json", return_value={"items": [{"snippet": {"customUrl": "@ViceOverdrive6"}}]}):
            self.assertTrue(pub.youtube_is_channel("fake", "@viceoverdrive6"))
            self.assertFalse(pub.youtube_is_channel("fake", "@another"))


class TextAndRightsTests(unittest.TestCase):
    def test_radar_texts_are_distinct_without_a_repeated_title_or_stock_question(self):
        topics = ("Erste Polizeiverfolgung nachts", "Monte hat kein Aim",
                  "Schräges Radio im Auto", "xQc klaut ein Auto",
                  "Monte startet das Spiel", "NPC kontert im Dialog",
                  "Monte fährt durch den Ort", "Sieht richtig geil aus")
        bodies = set()
        for topic in topics:
            with self.subTest(topic=topic):
                texts = build_texts({
                    "topic": topic, "hook": topic, "title": topic, "game": "gta6",
                    "streamer": "montanablack88",
                    "description": f"{topic}\nOriginalclip: https://clips.twitch.tv/Test",
                }, CFG)
                caption = texts["tiktok"]["caption"]
                description = texts["youtube"]["description"]
                body = caption.split("\n", 1)[0]
                self.assertIn(len(body.split()), range(20, 31))
                self.assertNotIn("Was hättet ihr gemacht", caption)
                self.assertLessEqual(caption.count(topic), 1)
                self.assertLessEqual(description.count(topic), 1)
                self.assertIn("Originalclip: https://clips.twitch.tv/Test", description)
                self.assertIn("https://www.twitch.tv/montanablack88", caption)
                self.assertEqual(len(texts["tiktok"]["hashtags"]), 5)
                self.assertEqual(len(texts["youtube"]["tags"]), 8)
                self.assertIn("#GTA6", caption)
                self.assertNotIn("#GTAV ", caption)
                bodies.add(body)
        self.assertEqual(len(bodies), len(topics))

    def test_texts_are_german_and_separate(self):
        t = build_texts({"topic": "Polizeiflucht am Strand", "keywords": ["Vice City"]}, CFG)
        self.assertTrue(t["youtube"]["title"].endswith("#Shorts"))
        self.assertLessEqual(len(t["youtube"]["title"]), 100)
        self.assertIn("#gta6 #gtavi #fyp #fy #viral", t["tiktok"]["caption"])
        self.assertNotEqual(t["youtube"]["description"], t["tiktok"]["caption"])

    def test_long_title_truncated(self):
        t = build_texts({"topic": "X" * 200}, CFG)
        self.assertLessEqual(len(t["youtube"]["title"]), 100)

    def test_rights_required(self):
        with self.assertRaises(RightsError):
            check_rights({"source": "x.mp4"})
        with self.assertRaises(RightsError):
            check_rights({"source": "x.mp4", "rights": {"type": "licensed"}})
        with self.assertRaises(RightsError):
            check_rights({"source": "https://clips.twitch.tv/abc", "rights": {"type": "own"}})
        self.assertEqual(check_rights({"source": "x.mp4", "rights": {"type": "own"}})["type"], "own")


class ClipperProgramTests(unittest.TestCase):
    def _cfg(self, proof="https://www.twitch.tv/videos/123?t=1h2m3s"):
        cfg = copy.deepcopy(CFG)
        for st in cfg["clip_allowlist"]["streamers"]:
            st["proof"] = proof
        cfg["clip_allowlist"]["streamers"][0]["required_tags"] = ["montepartner"]
        return cfg

    def _brief(self, streamer="montanablack88"):
        return {"source": "clip.mp4", "streamer": streamer, "rights": {"type": "clipper_program"},
                "topic": "Monte in Vice City"}

    def test_needs_allowlist_and_proof(self):
        with self.assertRaises(RightsError):
            check_rights(self._brief(), self._cfg(proof=""))            # Beleg fehlt
        with self.assertRaises(RightsError):
            check_rights(self._brief("fremderstreamer"), self._cfg())   # nicht in Allowlist
        r = check_rights(self._brief(), self._cfg())
        self.assertEqual(r["streamer"], "montanablack88")
        self.assertTrue(r["proof"])

    def test_credit_and_required_tags_in_every_text(self):
        t = build_texts(self._brief(), self._cfg())
        self.assertIn("https://www.twitch.tv/montanablack88", t["youtube"]["description"])
        self.assertIn("MontanaBlack", t["tiktok"]["caption"])
        self.assertIn("twitch.tv/montanablack88", t["tiktok"]["caption"])
        self.assertIn("#montepartner", t["tiktok"]["caption"])
        self.assertIn("montepartner", t["youtube"]["tags"])

    def test_long_caption_keeps_full_attribution_and_required_tags(self):
        brief = {**self._brief(), "caption": "X" * 5000}
        caption = build_texts(brief, self._cfg())["tiktok"]["caption"]
        self.assertLessEqual(len(caption), 2200)
        self.assertIn("MontanaBlack: https://www.twitch.tv/montanablack88", caption)
        self.assertIn("#montepartner", caption)

    def test_publish_blocks_clip_without_credit(self):
        cfg = self._cfg()
        t = build_texts({**self._brief("ishowspeed"), "topic": "Speed in GTA"}, cfg)
        self.assertIn("youtube.com/@IShowSpeed", t["tiktok"]["caption"])
        self.assertIn("https://www.youtube.com/@IShowSpeed", t["youtube"]["description"])
        m = {"short_id": "c", "rights": {"type": "clipper_program"}, "texts": {}, "published": {}}
        self.assertIn("Quellenangabe", blocked_reason(m, "youtube", {"youtube": {"approved": True}}))
        m["credit"] = "MontanaBlack – twitch.tv/montanablack88"
        self.assertIsNone(blocked_reason(m, "youtube", {"youtube": {"approved": True}}))


class PublishTests(unittest.TestCase):
    def _manifest(self, sid, rights="own"):
        return {"short_id": sid, "synthetic": rights == "synthetic", "rights": {"type": rights},
                "file": "short.mp4", "texts": build_texts({"topic": "Test"}, CFG), "published": {}}

    def test_synthetic_always_blocked(self):
        m = self._manifest("s", "synthetic")
        self.assertIn("synthetisch", blocked_reason(m, "youtube", {"youtube": {"approved": True}}))

    def test_requires_approval(self):
        m = self._manifest("o")
        self.assertEqual(blocked_reason(m, "tiktok", {"tiktok": {"approved": False}}), "nicht freigegeben")
        self.assertIsNone(blocked_reason(m, "tiktok", {"tiktok": {"approved": True}}))

    def test_payloads(self):
        m = self._manifest("o")
        yb = youtube_body(m, CFG)
        self.assertEqual(yb["status"]["privacyStatus"], "private")
        self.assertEqual(yb["snippet"]["defaultLanguage"], "de")
        inbox = tiktok_init_body(m, CFG, 1234)
        self.assertEqual(inbox, {"source_info": {"source": "FILE_UPLOAD", "video_size": 1234,
                                                 "chunk_size": 1234, "total_chunk_count": 1}})
        cfg = {**CFG, "tiktok": {"mode": "direct", "privacy_level": "SELF_ONLY"}}
        direct = tiktok_init_body(m, cfg, 1234, {"privacy_level_options": ["SELF_ONLY", "FOLLOWER_OF_CREATOR"]})
        self.assertEqual(direct["post_info"]["privacy_level"], "SELF_ONLY")
        self.assertEqual(direct["post_info"]["title"], m["texts"]["tiktok"]["caption"])
        with self.assertRaises(RuntimeError):
            tiktok_init_body(m, cfg, 1234, {"privacy_level_options": ["PUBLIC_TO_EVERYONE"]})

    def test_dry_run_batch_flow_makes_no_network_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for sid, rights in (("own1", "own"), ("syn1", "synthetic")):
                write_json(root / "shorts" / sid / "manifest.json", self._manifest(sid, rights))
            batch = make_batch(root / "shorts", root / "approvals")
            data = json.loads(batch.read_text())
            for i in data["items"]:
                i["youtube"]["approved"] = True
            write_json(batch, data)
            os.environ.pop("YT_REFRESH_TOKEN", None)
            res = {r["short_id"]: r for r in publish("youtube", root / "shorts", root / "approvals", root / "logs", CFG)}
            self.assertIsNone(res["own1"]["blocked"])
            self.assertEqual(res["own1"]["mode"], "dry-run")
            self.assertIn("synthetisch", res["syn1"]["blocked"])


class TikTokFlowTest(unittest.TestCase):
    """Simulierter Live-Ablauf gegen gefälschte TikTok-Antworten (kein Netzwerk)."""

    def test_inbox_uses_video_only_endpoint_and_polls_for_delivery(self):
        calls = []
        def api(path, token, body):
            calls.append((path, body))
            if path.endswith("/init/"):
                return {"publish_id": "p1", "upload_url": "https://open-upload.tiktokapis.com/test"}
            return {"status": "PROCESSING_UPLOAD" if len(calls) == 2 else "SEND_TO_USER_INBOX"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(pub, "_tt_call", side_effect=api), \
                patch.object(pub.urllib.request, "urlopen") as put, patch.object(pub.time, "sleep") as wait:
            video = Path(tmp) / "short.mp4"
            video.write_bytes(b"test")
            result = pub.tiktok_upload(video, {}, CFG, "fake")
        self.assertTrue(calls[0][0].endswith("/inbox/video/init/"))
        self.assertEqual(set(calls[0][1]), {"source_info"})
        self.assertEqual(result["status"], "SEND_TO_USER_INBOX")
        self.assertEqual(put.call_count, 1)
        wait.assert_called_once_with(3)

    def test_direct_flow_with_fake_api(self):
        calls, puts = [], []

        def fake_http(method, url, headers=None, params=None, body=None, form=None, timeout=30):
            calls.append(url)
            if url.endswith("/oauth/token/"):
                return {"access_token": "at", "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"]}
            if url.endswith("creator_info/query/"):
                return {"data": {"privacy_level_options": ["FOLLOWER_OF_CREATOR", "SELF_ONLY"],
                                 "max_video_post_duration_sec": 600}, "error": {"code": "ok"}}
            if url.endswith("/video/init/"):
                self.assertEqual(body["post_info"]["privacy_level"], "SELF_ONLY")
                return {"data": {"publish_id": "p1", "upload_url": "https://upload.invalid/x"}, "error": {"code": "ok"}}
            if url.endswith("status/fetch/"):
                return {"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}}
            raise AssertionError(url)

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=0):
            puts.append(dict(req.header_items()))
            return FakeResp()

        old_http, old_open = pub.http_json, pub.urllib.request.urlopen
        pub.http_json, pub.urllib.request.urlopen = fake_http, fake_urlopen
        os.environ.update(TIKTOK_CLIENT_KEY="k", TIKTOK_CLIENT_SECRET="s", TIKTOK_REFRESH_TOKEN="r")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                video = Path(tmp) / "short.mp4"
                video.write_bytes(b"x" * 1000)
                m = {"texts": build_texts({"topic": "Test"}, CFG), "video": {"duration": 20}}
                cfg = {**CFG, "tiktok": {"mode": "direct", "privacy_level": "SELF_ONLY"}}
                res = pub.tiktok_upload(video, m, cfg, pub.tiktok_access_token())
        finally:
            pub.http_json, pub.urllib.request.urlopen = old_http, old_open
            for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"):
                os.environ.pop(k, None)
        self.assertEqual(res["publish_id"], "p1")
        self.assertEqual(puts[0]["Content-range"], "bytes 0-999/1000")
        self.assertTrue(calls[2].endswith("/post/publish/video/init/"))



class YouTubeCheckTest(unittest.TestCase):
    def test_reports_missing_scope_and_wrong_channel_without_secrets(self):
        from vo import youtube_check
        env = {"YT_CLIENT_ID": "id", "YT_CLIENT_SECRET": "geheim", "YT_REFRESH_TOKEN": "rt"}

        def fake_http(method, url, **kw):
            if "tokeninfo" in url:
                return {"scope": "https://www.googleapis.com/auth/youtube.upload"}
            raise RuntimeError('HTTP 403 bei GET x: ACCESS_TOKEN_SCOPE_INSUFFICIENT')

        with patch.dict(os.environ, env), \
                patch.object(youtube_check, "youtube_access_token", return_value="tok-xyz"), \
                patch.object(youtube_check, "http_json", side_effect=fake_http), \
                patch("builtins.print") as out:
            self.assertEqual(youtube_check.check("@viceoverdrive6"), 1)
        text = " ".join(str(c.args[0]) for c in out.call_args_list)
        self.assertIn("YT_PREFLIGHT_SCOPE_MISSING: youtube.readonly", text)
        self.assertIn("YT_PREFLIGHT_CHANNEL_SCOPE_MISSING", text)
        self.assertNotIn("tok-xyz", text)
        self.assertNotIn("geheim", text)


class ActionsUploadGuardTest(unittest.TestCase):
    def test_even_authorized_actions_cannot_publish_to_youtube_or_direct_post(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "VO_ACTIONS_UPLOAD": "1"}):
            for cfg, mode, inbox in ((CFG, "public", False),
                                     ({**CFG, "tiktok": {"mode": "direct", "privacy_level": "SELF_ONLY"}},
                                      "off", True)):
                with self.subTest(mode=mode, tiktok=cfg["tiktok"]["mode"]), self.assertRaises(ValueError):
                    run_cycle(cfg, Path(tmp), mode=mode, tiktok_inbox=inbox,
                              radar=lambda *a: self.fail("Kein Netzwerk"))

    def test_live_upload_on_actions_needs_autopilot_workflow_flag(self):
        from vo.autopilot import run_cycle
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "VO_ACTIONS_UPLOAD": ""}):
            with self.assertRaises(ValueError):
                run_cycle(CFG, Path(tmp), mode="private", radar=lambda *a: self.fail("kein Radar"))


if __name__ == "__main__":
    unittest.main()
