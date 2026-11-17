"""Offline-Tests (kein Netzwerk, keine Secrets)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vo.common import load_config, write_json  # noqa: E402
from vo.publish import blocked_reason, buffer_input, make_batch, publish, youtube_body  # noqa: E402
from vo.render import RightsError, check_rights  # noqa: E402
from vo.texts import build_texts  # noqa: E402
from vo.twitch import Helix, dedupe, run_radar  # noqa: E402

CFG = load_config()
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def clip(cid, bid, views, *, video="v1", offset=100, title="Krasser Moment", lang="de", hours_ago=2):
    return {"id": cid, "url": f"https://clips.twitch.tv/{cid}", "broadcaster_id": bid,
            "broadcaster_name": f"user{bid}", "title": title, "language": lang, "view_count": views,
            "video_id": video, "vod_offset": offset, "duration": 30.0,
            "created_at": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")}


class FakeTwitch:
    """Simuliert Helix-Antworten. views wird zwischen zwei Läufen angepasst."""

    def __init__(self):
        self.calls = []
        self.views = {"a": 1000, "b": 400, "c": 900, "d": 50}

    def __call__(self, method, url, headers=None, params=None, form=None, body=None, timeout=30):
        self.calls.append((method, url, params))
        if "oauth2/token" in url:
            return {"access_token": "fake"}
        if url.endswith("/users"):
            return {"data": [{"id": str(i), "login": l} for i, (_, l) in enumerate(params, 1)]}
        if url.endswith("/games"):
            return {"data": [{"id": "999", "name": params["name"]}]}
        if url.endswith("/clips"):
            v = self.views
            if params.get("broadcaster_id") == "1":
                return {"data": [clip("a", "1", v["a"]), clip("a2", "1", v["a"] - 10, offset=110)]}
            if params.get("broadcaster_id") == "2":
                return {"data": [clip("b", "2", v["b"], video="v2")]}
            if params.get("game_id") == "999":
                return {"data": [clip("a", "1", v["a"]),  # Duplikat über Kategorie
                                 clip("c", "77", v["c"], video="v7"),
                                 clip("d", "78", v["d"], video="v8"),
                                 clip("en", "79", 5000, video="v9", lang="en")]}
            return {"data": []}
        raise AssertionError(url)


class RadarTests(unittest.TestCase):
    def test_dedupe_merges_same_vod_window_and_same_id(self):
        groups = dedupe([clip("x", "1", 10), clip("y", "1", 20, offset=115), clip("z", "1", 5, offset=500, title="anders"),
                         {**clip("x", "1", 10), "found_via": ["kategorie:de"]}])
        ids = {g["id"]: g for g in groups}
        self.assertEqual(set(ids), {"y", "z"})
        self.assertIn("x", ids["y"]["duplicates"])

    def test_radar_ranks_by_view_growth_and_filters_language(self):
        fake = FakeTwitch()
        client = Helix("id", "secret", fetch=fake)
        with tempfile.TemporaryDirectory() as tmp:
            state, out = Path(tmp) / "state.json", Path(tmp) / "radar"
            r1 = run_radar(CFG, state, out, client=client, now=NOW)
            ids1 = [c["id"] for c in r1["top"]]
            self.assertNotIn("en", ids1)                 # nur deutschsprachig
            self.assertNotIn("a2", ids1)                 # Duplikat zusammengefasst
            self.assertEqual(ids1[0], "a")
            a = next(c for c in r1["top"] if c["id"] == "a")
            self.assertIn("kategorie:de", a["found_via"])
            self.assertIn("watchlist:montanablack88", a["found_via"])
            # Zweiter Check: c wächst stark, a kaum → c muss vorn liegen
            fake.views.update({"a": 1010, "c": 1900, "b": 450, "d": 50})
            r2 = run_radar(CFG, state, out, client=client, now=NOW + timedelta(hours=1))
            self.assertEqual([c["id"] for c in r2["top"]][:3], ["c", "b", "a"])
            self.assertEqual(r2["top"][0]["view_delta"], 1000)
            self.assertNotIn("d", [c["id"] for c in r2["top"]])  # kein Zuwachs
            self.assertTrue(list(out.glob("radar-*.md")))
            logins = [p for m, u, p in fake.calls if u.endswith("/users")][0]
            self.assertEqual([l for _, l in logins], CFG["twitch_watchlist"])


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
        bi = buffer_input(m, CFG, "chan")
        self.assertEqual(bi["mode"], "addToQueue")
        self.assertEqual(bi["text"], m["texts"]["tiktok"]["caption"])

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


if __name__ == "__main__":
    unittest.main()
