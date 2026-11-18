"""Twitch-Radar: findet GTA-Clips der Streamer aus der Allowlist (config.json → clip_allowlist).

Nur zum ENTDECKEN. Es werden keine Clips heruntergeladen oder geschnitten.
Gesucht wird ausschließlich bei Kanälen der Allowlist; mit gta_filter bleiben nur
Clips aus den GTA-Kategorien (GTA V inkl. RP, GTA VI). Clips anderer Kanäle oder
Spiele werden verworfen und nur gezählt.

Rangfolge: Zuwachs der Aufrufe seit dem letzten Check (view_delta),
bei Gleichstand die Aufrufe pro Stunde (velocity).
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from . import allowlist
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

    def game_ids(self, names: list[str]) -> dict[str, str]:
        """Kategorie-Name → Twitch-ID (unbekannte Namen fehlen im Ergebnis)."""
        if not names:
            return {}
        return {g["name"]: g["id"] for g in self.get("games", [("name", n) for n in names])}

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


_NO_YT = object()


def run_radar(cfg: dict, state_path: Path, out_dir: Path, client: Helix | None = None, now=None,
              youtube=_NO_YT) -> dict:
    """youtube: YouTubeReader, None (YouTube auslassen) oder weglassen (aus Umgebung lesen)."""
    client = client or Helix.from_env()
    now = now or now_utc()
    rcfg = cfg["radar"]
    state = read_json(state_path, {"last_check": None, "clips": {}})
    since = (parse_iso(state["last_check"]) if state.get("last_check")
             else now - timedelta(hours=rcfg["lookback_hours_first_run"]))
    # Clips, die schon bekannt sind, bleiben 7 Tage im Blick, damit ihr Zuwachs messbar ist.
    window_start = min(since, now - timedelta(days=7)) if state.get("clips") else since
    started_at, ended_at = iso(window_start), iso(now)

    wanted = allowlist.logins(cfg)
    if not wanted:
        raise SystemExit("clip_allowlist in config.json ist leer – keine Kanäle zum Suchen.")
    users = [u for u in client.users(wanted) if u["login"].lower() in wanted]
    missing_logins = sorted(set(wanted) - {u["login"].lower() for u in users})

    gcfg = cfg.get("gta_filter", {})
    gta_ids: dict[str, str] = {}
    if gcfg.get("enabled"):
        gta_ids = client.game_ids(gcfg.get("categories", []))
        if not gta_ids:
            raise SystemExit("gta_filter: keine der Kategorien bei Twitch gefunden: "
                             f"{gcfg.get('categories')}")
    allowed_games = set(gta_ids.values())

    found: list[dict] = []
    skipped_not_gta = 0
    for user in users:
        for clip in client.clips(broadcaster_id=user["id"], started_at=started_at,
                                 ended_at=ended_at, first=rcfg["max_clips_per_source"]):
            if clip.get("broadcaster_id") != user["id"]:
                continue
            if allowed_games and clip.get("game_id") not in allowed_games:
                skipped_not_gta += 1
                continue
            found.append({**clip, "platform": "twitch", "found_via": [f"allowlist:{user['login'].lower()}"],
                          "streamer_login": user["login"].lower()})

    yt_info = {"status": "übersprungen (Secret YT_API_KEY fehlt)", "missing_handles": [],
               "skipped_not_gta": 0, "found": 0}
    if youtube is _NO_YT:
        from .youtube_radar import YouTubeReader
        youtube = YouTubeReader.from_env()
    if youtube is not None:
        from .youtube_radar import find_videos
        try:
            yt = find_videos(cfg, youtube, window_start, gta_only=bool(gcfg.get("enabled")))
        except RuntimeError:  # Keine API-Antwort mit möglichen Geheimnissen in den Bericht schreiben
            yt_info["status"] = "FEHLER: YouTube-Suche fehlgeschlagen (API-Zugriff prüfen)"
        else:
            found.extend(yt["found"])
            yt_info = {"status": "ok", "missing_handles": yt["missing_handles"],
                       "skipped_not_gta": yt["skipped_not_gta"], "found": len(yt["found"])}

    unique = dedupe(found, rcfg["dedupe_window_seconds"])
    ranked = [c for c in rank(unique, state, now) if c["view_delta"] >= rcfg["min_view_delta"]]
    top = ranked[: rcfg["top_n"]]

    report = {
        "checked_at": iso(now),
        "previous_check": state.get("last_check"),
        "window": [started_at, ended_at],
        "allowlist": wanted,
        "missing_logins": missing_logins,
        "gta_categories": gta_ids,
        "skipped_not_gta": skipped_not_gta,
        "youtube": yt_info,
        "raw_found": len(found),
        "after_dedupe": len(unique),
        "hinweis": "Nur Kanäle aus der Allowlist. Schnitt erst, wenn für den Streamer ein Beleg (proof) in config.json steht.",
        "top": [{k: c.get(k) for k in (
            "id", "url", "platform", "broadcaster_name", "streamer_login", "game_id", "title", "language", "view_count", "view_delta",
            "velocity_per_hour", "is_new", "created_at", "duration", "found_via", "duplicates",
            "game", "video_id", "vod_offset")}
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
             f"{report['raw_found']} GTA-Treffer → {report['after_dedupe']} nach Duplikat-Abgleich · "
             f"{report['skipped_not_gta']} Clips aus anderen Spielen verworfen", "",
             f"Allowlist: {', '.join(wanted)}"
             + (f" · **bei Twitch nicht gefunden: {', '.join(missing_logins)}**" if missing_logins else ""), "",
             f"YouTube: {yt_info['status']} · {yt_info['found']} GTA-Videos · {yt_info['skipped_not_gta']} ohne GTA verworfen"
             + (f" · **Handle nicht gefunden: {', '.join(yt_info['missing_handles'])}**" if yt_info["missing_handles"] else ""), "",
             "> " + report["hinweis"], "",
             "| # | Zuwachs | /h | Aufrufe | Plattform | Kanal | Titel | Quelle |", "|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(report["top"], 1):
        title = (c["title"] or "").replace("|", "/")
        lines.append(f"| {i} | +{c['view_delta']} | {c['velocity_per_hour']} | {c['view_count']} | "
                     f"{c.get('platform') or 'twitch'} | {c['broadcaster_name']} | [{title}]({c['url']}) | {', '.join(c['found_via'])} |")
    (out_dir / f"radar-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
