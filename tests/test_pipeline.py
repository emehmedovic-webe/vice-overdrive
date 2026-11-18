"""Offline-Tests (kein Netzwerk, keine Secrets)."""
import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vo import allowlist  # noqa: E402
from vo.common import load_config, write_json  # noqa: E402
import vo.publish as pub  # noqa: E402
from vo.publish import blocked_reason, make_batch, publish, tiktok_init_body, youtube_body  # noqa: E402
from vo.render import RightsError, check_rights  # noqa: E402
from vo.texts import build_texts  # noqa: E402
from vo.twitch import Helix, dedupe, run_radar  # noqa: E402
from vo.youtube_radar import YouTubeReader, is_gta  # noqa: E402

CFG = load_config()
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
                                 clip("chat", "1", 99999, video="v5", game="509658")]}  # Just Chatting
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
                return {"items": [{"contentDetails": {"videoId": params["playlistId"] + n}} for n in ("1", "2", "3")]}
            if url.endswith("/videos"):
                out = []
                for vid in params["id"].split(","):
                    title = {"1": "GTA 6 RP Chaos", "2": "Minecraft Stream", "3": "Grand Theft Auto alt"}[vid[-1]]
                    hours = 400 if vid.endswith("3") else 3
                    out.append({"id": vid, "snippet": {"title": title, "description": "", "channelTitle": vid[2:-1],
                                "publishedAt": (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                                "statistics": {"viewCount": "5000" if "IShowSpeed" in vid else "300"},
                                "contentDetails": {"duration": "PT45S"}})
                return {"items": out}
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            r = run_radar(CFG, Path(tmp) / "s.json", Path(tmp) / "r", client=Helix("i", "s", fetch=FakeTwitch()),
                          now=NOW, youtube=YouTubeReader(api_key="k", fetch=fake_yt))
            yt = [c for c in r["top"] if c["platform"] == "youtube"]
            self.assertEqual({c["id"] for c in yt}, {"yt:UUIShowSpeed1", "yt:UUMontanaBlack1", "yt:UUEligella1"})
            self.assertEqual(r["top"][0]["id"], "yt:UUIShowSpeed1")   # meiste Aufrufe vorn
            self.assertEqual(r["top"][0]["streamer_login"], "ishowspeed")
            self.assertEqual(r["youtube"]["missing_handles"], ["@xQc"])
            self.assertEqual(r["youtube"]["skipped_not_gta"], 3)       # Minecraft je Kanal
            self.assertFalse([u for _, u, _ in calls if u.endswith("/search")])  # kein teures search.list
            self.assertIn("Handle nicht gefunden: @xQc", next(Path(tmp, "r").glob("*.md")).read_text())

    def test_gta_detection(self):
        self.assertTrue(is_gta({"snippet": {"title": "Monte in GTA RP"}}))
        self.assertTrue(is_gta({"snippet": {"title": "x", "tags": ["Grand Theft Auto VI"]}}))
        self.assertFalse(is_gta({"snippet": {"title": "Fortnite mit Freunden"}}))

    def test_inactive_streamer_not_searched(self):
        cfg = copy.deepcopy(CFG)
        cfg["clip_allowlist"]["streamers"].append({"twitch_login": "nurvorgemerkt", "name": "X", "active": False})
        self.assertNotIn("nurvorgemerkt", allowlist.logins(cfg))


class TextAndRightsTests(unittest.TestCase):
    def test_texts_are_german_and_separate(self):
        t = build_texts({"topic": "Polizeiflucht am Strand", "keywords": ["Vice City"]}, CFG)
        self.assertTrue(t["youtube"]["title"].endswith("#Shorts"))
        self.assertLessEqual(len(t["youtube"]["title"]), 100)
        self.assertIn("#gta6deutsch", t["tiktok"]["caption"])
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


if __name__ == "__main__":
    unittest.main()
