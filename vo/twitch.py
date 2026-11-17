"""Twitch-Radar: findet interessante deutschsprachige GTA-VI-Clips.

Nur zum ENTDECKEN. Es werden keine Clips heruntergeladen oder geschnitten.
Was davon in ein Short darf, entscheidet eine Freigabe des Rechteinhabers
(siehe briefs/ und rights-Feld).

Rangfolge: Zuwachs der Aufrufe seit dem letzten Check (view_delta),
bei Gleichstand die Aufrufe pro Stunde (velocity).
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from .common import http_json, iso, now_utc, parse_iso, read_json, secret, write_json

HELIX = "https://api.twitch.tv/helix"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class Helix:
    """Minimaler Helix-Client (App-Access-Token per Client-Credentials, kostenlos)."""

    def __init__(self, client_id: str, client_secret: str, fetch=http_json):
        self.client_id = client_id
        self.client_secret = client_secret
        self.fetch = fetch
        self._token = None

    @classmethod
    def from_env(cls):
        return cls(secret("TWITCH_CLIENT_ID"), secret("TWITCH_CLIENT_SECRET"))

    def token(self) -> str:
        if not self._token:
            data = self.fetch("POST", TOKEN_URL, form={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            })
            self._token = data["access_token"]
        return self._token

    def get(self, path: str, params) -> list[dict]:
        headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {self.token()}"}
        return self.fetch("GET", f"{HELIX}/{path}", headers=headers, params=params).get("data", [])

    def users(self, logins: list[str]) -> list[dict]:
        return self.get("users", [("login", l) for l in logins])

    def game_id(self, name: str) -> str | None:
        data = self.get("games", {"name": name})
        return data[0]["id"] if data else None

    def clips(self, *, broadcaster_id=None, game_id=None, started_at, ended_at, first=50):
        params = {"started_at": started_at, "ended_at": ended_at, "first": first}
        if broadcaster_id:
            params["broadcaster_id"] = broadcaster_id
        if game_id:
            params["game_id"] = game_id
        return self.get("clips", params)


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", title.lower()).strip()


def dedupe(clips: list[dict], window: int = 30) -> list[dict]:
    """Fasst Duplikate zusammen.

    Gleich gilt: gleiche Clip-ID, oder gleicher Kanal + gleiches VOD und
    Startpunkte höchstens `window` Sekunden auseinander, oder gleicher Kanal
    + gleicher normalisierter Titel.
    Der Clip mit den meisten Aufrufen bleibt, die anderen landen in `duplicates`.
    """
    groups: list[dict] = []
    for clip in sorted(clips, key=lambda c: c.get("view_count", 0), reverse=True):
        match = None
        for g in groups:
            lead = g
            if clip["id"] == lead["id"] or clip["id"] in lead["duplicates"]:
                match = g
                break
            same_channel = clip.get("broadcaster_id") == lead.get("broadcaster_id")
            same_vod = (clip.get("video_id") and clip.get("video_id") == lead.get("video_id")
                        and clip.get("vod_offset") is not None and lead.get("vod_offset") is not None
                        and abs(clip["vod_offset"] - lead["vod_offset"]) <= window)
            same_title = same_channel and _norm_title(clip.get("title", "")) == _norm_title(lead.get("title", ""))
            if same_channel and (same_vod or same_title):
                match = g
                break
        if match is None:
            groups.append({**clip, "duplicates": [], "found_via": list(clip.get("found_via", []))})
        else:
            if clip["id"] != match["id"] and clip["id"] not in match["duplicates"]:
                match["duplicates"].append(clip["id"])
            for via in clip.get("found_via", []):
                if via not in match["found_via"]:
                    match["found_via"].append(via)
    return groups


def rank(clips: list[dict], state: dict, now) -> list[dict]:
    seen = state.get("clips", {})
    ranked = []
    for c in clips:
        prev = seen.get(c["id"])
        if prev:
            delta = c["view_count"] - prev["view_count"]
            hours = max((now - parse_iso(prev["checked_at"])).total_seconds() / 3600, 1 / 60)
        else:
            delta = c["view_count"]  # neu seit letztem Check: alle Aufrufe sind Zuwachs
            hours = max((now - parse_iso(c["created_at"])).total_seconds() / 3600, 1 / 60)
        ranked.append({**c, "view_delta": delta, "velocity_per_hour": round(delta / hours, 1),
                       "is_new": prev is None})
    ranked.sort(key=lambda c: (c["view_delta"], c["velocity_per_hour"]), reverse=True)
    return ranked


def run_radar(cfg: dict, state_path: Path, out_dir: Path, client: Helix | None = None, now=None) -> dict:
    client = client or Helix.from_env()
    now = now or now_utc()
    rcfg = cfg["radar"]
    state = read_json(state_path, {"last_check": None, "clips": {}})
    since = (parse_iso(state["last_check"]) if state.get("last_check")
             else now - timedelta(hours=rcfg["lookback_hours_first_run"]))
    # Clips, die schon bekannt sind, bleiben 7 Tage im Blick, damit ihr Zuwachs messbar ist.
    window_start = min(since, now - timedelta(days=7)) if state.get("clips") else since
    started_at, ended_at = iso(window_start), iso(now)

    found: list[dict] = []
    for user in client.users(cfg["twitch_watchlist"]):
        for clip in client.clips(broadcaster_id=user["id"], started_at=started_at,
                                 ended_at=ended_at, first=rcfg["max_clips_per_source"]):
            found.append({**clip, "found_via": [f"watchlist:{user['login']}"]})

    gid = client.game_id(cfg["discovery_category"])
    if gid:
        for clip in client.clips(game_id=gid, started_at=started_at, ended_at=ended_at,
                                 first=100):
            if clip.get("language") == cfg["language"]:
                found.append({**clip, "found_via": ["kategorie:de"]})

    unique = dedupe(found, rcfg["dedupe_window_seconds"])
    ranked = [c for c in rank(unique, state, now) if c["view_delta"] >= rcfg["min_view_delta"]]
    top = ranked[: rcfg["top_n"]]

    report = {
        "checked_at": iso(now),
        "previous_check": state.get("last_check"),
        "window": [started_at, ended_at],
        "game_id": gid,
        "raw_found": len(found),
        "after_dedupe": len(unique),
        "hinweis": "Nur zum Entdecken. Clips nicht herunterladen oder verwenden ohne Freigabe des Rechteinhabers.",
        "top": [{k: c.get(k) for k in (
            "id", "url", "broadcaster_name", "title", "language", "view_count", "view_delta",
            "velocity_per_hour", "is_new", "created_at", "duration", "found_via", "duplicates")}
            for c in top],
    }
    for c in unique:
        state["clips"][c["id"]] = {"view_count": c["view_count"], "checked_at": iso(now)}
        for dup in c["duplicates"]:
            state["clips"].pop(dup, None)
    cutoff = now - timedelta(days=14)
    state["clips"] = {k: v for k, v in state["clips"].items() if parse_iso(v["checked_at"]) >= cutoff}
    state["last_check"] = iso(now)
    write_json(state_path, state)

    stamp = now.strftime("%Y%m%d-%H%M")
    write_json(out_dir / f"radar-{stamp}.json", report)
    lines = [f"# Twitch-Radar {report['checked_at']}", "",
             f"Seit letztem Check: {report['previous_check'] or 'erster Lauf'} · "
             f"{report['raw_found']} Treffer → {report['after_dedupe']} nach Duplikat-Abgleich", "",
             "> " + report["hinweis"], "",
             "| # | Zuwachs | /h | Aufrufe | Kanal | Titel | Quelle |", "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(report["top"], 1):
        title = (c["title"] or "").replace("|", "/")
        lines.append(f"| {i} | +{c['view_delta']} | {c['velocity_per_hour']} | {c['view_count']} | "
                     f"{c['broadcaster_name']} | [{title}]({c['url']}) | {', '.join(c['found_via'])} |")
    (out_dir / f"radar-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
