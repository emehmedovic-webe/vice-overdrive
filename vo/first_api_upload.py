"""Einmaliger API-Test mit genau einem explizit ausgewählten Short."""
from pathlib import Path
from os import environ

from . import allowlist
from .common import load_config, read_json
from .publish import _tt_call, tiktok_upload, youtube_access_token, youtube_body, youtube_is_channel, youtube_upload
from .texts import build_texts

cfg = load_config()
sid = "twitch-EnchantingNimbleMuleCharlietheUnicorn-L6-gkH3hiA0UlDd7"
out = Path("/tmp/vo-upload/shorts") / sid
video = out / "short.mp4"
m = read_json(out / "manifest.json", {})
entry = allowlist.find(cfg, m.get("streamer"))
if (not entry or not entry.get("active", True) or not allowlist.has_proof(entry)
        or m.get("short_id") != sid or m.get("synthetic")
        or m.get("rights", {}).get("type") != "clipper_program" or not video.is_file()
        or m.get("video", {}).get("width") != 1080 or m.get("video", {}).get("height") != 1920
        or not 0 < m.get("video", {}).get("duration", 0) <= 60):
    raise SystemExit("ABBRUCH: Herkunft, Rechte oder Shorts-Format konnten nicht bestätigt werden.")

brief = {
    "streamer": "xrohat", "game": "gta5", "scene": "roleplay",
    "topic": "GTA RP", "title": "Schilder hoch: Auflauf bei Rohat im GTA-RP",
    "hook": "Auf einmal steht da eine ganze Menschenmenge",
    "description": "In Rohats GTA-RP-Clip versammelt sich nachts eine Menschenmenge mit Schildern. "
                   "Vorne stehen zwei Figuren mit dem Rücken zur Kamera und schauen zu.\n\n"
                   "Was hättet ihr in der Situation gemacht?\n\nOriginalclip: " + m["source"],
    "caption": "Nachts im GTA-RP und plötzlich stehen da überall Leute mit Schildern. "
               "Würdet ihr stehen bleiben oder lieber weitergehen?",
}
m["texts"] = build_texts(brief, cfg)
cfg["youtube"]["privacy_status"] = "private"
try:
    yt = youtube_access_token()
    if not youtube_is_channel(yt, cfg["youtube_channel"]):
        print("YOUTUBE_BLOCKED_WRONG_CHANNEL")
    else:
        vid = youtube_upload(video, youtube_body(m, cfg), yt)
        print("YOUTUBE_UPLOADED_PRIVATE", vid)
except (OSError, RuntimeError, ValueError, KeyError, SystemExit):
    print("YOUTUBE_NOT_CONFIRMED_AUTH_OR_API")

# Kein Refresh auf einem flüchtigen Runner: dort kann ein rotierter Token nicht sicher gespeichert werden.
tok = environ.get("TIKTOK_ACCESS_TOKEN")
if not tok:
    print("TIKTOK_BLOCKED_NO_CURRENT_ACCESS_TOKEN")
elif cfg["tiktok"]["mode"] != "inbox":
    print("TIKTOK_BLOCKED_NOT_INBOX")
else:
    try:
        who = _tt_call("creator_info/query/", tok, {})
        if who.get("creator_username", "").lstrip("@").casefold() != cfg["tiktok_account"].lstrip("@").casefold():
            print("TIKTOK_BLOCKED_WRONG_ACCOUNT")
        else:
            result = tiktok_upload(video, m, cfg, tok)
            print("TIKTOK_INBOX_ACCEPTED", result.get("status") or "processing")
    except (OSError, RuntimeError, ValueError, KeyError, SystemExit):
        print("TIKTOK_NOT_CONFIRMED_AUTH_OR_API")
