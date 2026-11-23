"""Nur-Lese-Recherche: meistgesehene GTA-6-Shorts der letzten Wochen (YouTube Data API, YT_API_KEY).

Kostet ~100 Einheiten pro Suchbegriff (search.list) + 1 pro videos.list-Aufruf.
Lädt nichts hoch, schreibt nur einen Markdown-Bericht nach data/research/shorts.md.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .youtube_radar import YouTubeReader

QUERIES = [
    ("gta 6 #shorts", None), ("gta 6 shorts", "de"), ("gta 6 montanablack", "de"),
    ("gta 6 trymacs", "de"), ("gta 6 rohat", "de"), ("gta 6 streamer reaction", None),
    ("gta 6 funny moments", None), ("gta 6 clip", "de"),
]


def _seconds(iso: str) -> int:
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def run(out: Path, days: int = 30) -> str:
    yt = YouTubeReader.from_env()
    if not yt:
        raise SystemExit("YT_API_KEY fehlt")
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: dict[str, str] = {}
    for q, lang in QUERIES:
        params = {"part": "id", "q": q, "type": "video", "videoDuration": "short",
                  "order": "viewCount", "publishedAfter": after, "maxResults": 50}
        if lang:
            params["relevanceLanguage"] = lang
        try:
            for it in yt.get("search", params).get("items", []):
                ids.setdefault(it["id"]["videoId"], q)
        except Exception as exc:  # Kontingent o. Ä.
            print(f"Suche '{q}' fehlgeschlagen: {exc}")
    vids = []
    idl = list(ids)
    for i in range(0, len(idl), 50):
        vids += yt.videos(idl[i:i + 50])
    rows = []
    for v in vids:
        sec = _seconds(v["contentDetails"]["duration"])
        if sec > 180:
            continue
        st, sn = v.get("statistics", {}), v["snippet"]
        views = int(st.get("viewCount", 0))
        likes = int(st.get("likeCount", 0) or 0)
        comments = int(st.get("commentCount", 0) or 0)
        rows.append((views, likes, comments, sec, sn["channelTitle"], sn["title"].replace("|", "/"),
                     sn["publishedAt"][:10], v["id"], ids[v["id"]], sn.get("defaultAudioLanguage", ""),
                     " ".join(sn.get("tags", [])[:8])))
    rows.sort(reverse=True)
    lines = [f"# GTA-6-Shorts, meistgesehen seit {after[:10]} ({len(rows)} Videos)", "",
             "| Views | Likes | Kom. | Sek | Kanal | Titel | Datum | Sprache | Link | Suchbegriff |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows[:120]:
        lines.append(f"| {r[0]:,} | {r[1]:,} | {r[2]:,} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[9]} | "
                     f"https://youtube.com/shorts/{r[7]} | {r[8]} |")
    lines += ["", "## Tags der Top 40", ""]
    lines += [f"- {r[7]}: {r[10]}" for r in rows[:40]]
    # Kanal-Statistik
    agg: dict[str, list[int]] = {}
    for r in rows:
        agg.setdefault(r[4], []).append(r[0])
    lines += ["", "## Kanäle nach Gesamtviews (Top 25)", ""]
    for ch, vs in sorted(agg.items(), key=lambda kv: -sum(kv[1]))[:25]:
        lines.append(f"- {ch}: {sum(vs):,} Views in {len(vs)} Shorts")
    text = "\n".join(lines) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(run(Path(os.environ.get("OUT", "data/research/shorts.md"))))
