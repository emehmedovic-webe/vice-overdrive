"""YouTube-Radar: neue GTA-Videos der Allowlist-Streamer auf YouTube (nur LESEN, nie hochladen).

Nutzt die YouTube Data API v3 im kostenlosen Kontingent (10.000 Einheiten/Tag):
pro Kanal 1 Einheit für channels.list (Handle → Upload-Playlist), 1 für playlistItems.list,
1 für videos.list (Aufrufe, Länge, Tags). Ein Lauf mit 5 Kanälen kostet also ~15 Einheiten.
Zum Vergleich: search.list würde 100 Einheiten pro Aufruf kosten und wird deshalb nicht genutzt.

Anmeldung: YT_API_KEY (API-Schlüssel, liest nur öffentliche Daten, kostenlos, ohne Abrechnung).
Der Upload-Zugang (YT_REFRESH_TOKEN) reicht NICHT: Er hat nur die Berechtigung youtube.upload,
Google lehnt Lesezugriffe damit ab (getestet 2026-11-18: 403 ACCESS_TOKEN_SCOPE_INSUFFICIENT).
Ohne YT_API_KEY wird YouTube übersprungen.
"""
from __future__ import annotations

import os
import re

from . import allowlist
from .common import http_json, parse_iso

API = "https://www.googleapis.com/youtube/v3"
GTA_PATTERN = re.compile(r"\bgta\s*(v|5|vi|6|rp|online)?\b|grand theft auto|\bvice city\b", re.I)


class YouTubeReader:
    def __init__(self, *, api_key: str | None = None, token: str | None = None, fetch=http_json):
        if not api_key and not token:
            raise ValueError("api_key oder token nötig")
        self.api_key, self.token, self.fetch = api_key, token, fetch

    @classmethod
    def from_env(cls):
        key = os.environ.get("YT_API_KEY", "").strip()
        return cls(api_key=key) if key else None

    def get(self, path: str, params: dict) -> dict:
        headers = {}
        params = dict(params)
        if self.api_key:
            params["key"] = self.api_key
        else:
            headers["Authorization"] = f"Bearer {self.token}"
        return self.fetch("GET", f"{API}/{path}", headers=headers, params=params)

    def channel(self, handle: str) -> dict | None:
        items = self.get("channels", {"part": "snippet,contentDetails", "forHandle": handle}).get("items", [])
        return items[0] if items else None

    def recent_video_ids(self, uploads_playlist: str, n: int) -> list[str]:
        items = self.get("playlistItems", {"part": "contentDetails", "playlistId": uploads_playlist,
                                           "maxResults": min(n, 50)}).get("items", [])
        return [i["contentDetails"]["videoId"] for i in items]

    def videos(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        return self.get("videos", {"part": "snippet,statistics,contentDetails",
                                   "id": ",".join(ids)}).get("items", [])


def _seconds(iso_duration: str) -> float:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    if not m:
        return 0.0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + s)


def is_gta(video: dict) -> bool:
    sn = video.get("snippet", {})
    text = " ".join([sn.get("title", ""), sn.get("description", "")[:500], " ".join(sn.get("tags", []))])
    return bool(GTA_PATTERN.search(text))


def find_videos(cfg: dict, reader: YouTubeReader, since, *, gta_only: bool = True) -> dict:
    """Liefert Radar-Einträge im selben Format wie Twitch-Clips."""
    per_channel = cfg.get("radar", {}).get("youtube_videos_per_channel", 15)
    found, missing, skipped = [], [], 0
    for st in allowlist.streamers(cfg):
        handle = st.get("youtube_handle")
        if not handle:
            continue
        ch = reader.channel(handle)
        if not ch:
            missing.append(handle)
            continue
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        for v in reader.videos(reader.recent_video_ids(uploads, per_channel)):
            sn = v["snippet"]
            if sn.get("channelId") != ch["id"] or sn.get("liveBroadcastContent") in {"live", "upcoming"}:
                continue
            if parse_iso(sn["publishedAt"]) < since:
                continue
            if gta_only and not is_gta(v):
                skipped += 1
                continue
            dur = _seconds(v.get("contentDetails", {}).get("duration", ""))
            found.append({
                "id": f"yt:{v['id']}", "url": f"https://www.youtube.com/watch?v={v['id']}",
                "platform": "youtube", "broadcaster_id": f"yt:{ch['id']}",
                "broadcaster_name": sn.get("channelTitle", st["name"]),
                "streamer_login": st["twitch_login"].lower(), "title": sn.get("title", ""),
                "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
                "view_count": int(v.get("statistics", {}).get("viewCount", 0)),
                "created_at": sn["publishedAt"], "duration": dur, "is_short": dur <= 60,
                "video_id": None, "vod_offset": None, "game_id": None,
                "found_via": [f"youtube:{handle}"],
            })
    return {"found": found, "missing_handles": missing, "skipped_not_gta": skipped}
