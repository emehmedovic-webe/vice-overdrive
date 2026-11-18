"""YouTube-Zugang prüfen, ohne etwas hochzuladen.

Gibt nur Statuscodes, die erteilten Berechtigungen und den Kanal-Handle aus,
nie Token oder Secrets.
"""
import re
from os import environ

from .common import http_json
from .publish import youtube_access_token, youtube_is_channel

NEEDED = ("https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly")


def check(expected_handle: str) -> int:
    if not all(environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        print("YT_PREFLIGHT_MISSING_SECRETS")
        return 1
    try:
        token = youtube_access_token()
    except Exception as exc:  # Antwort nicht ausgeben, kann Token-Teile enthalten
        text = str(exc)
        if "invalid_grant" in text:
            print("YT_PREFLIGHT_REFRESH_INVALID_GRANT (Token widerrufen/abgelaufen oder von anderer Client-ID)")
        elif "invalid_client" in text or "unauthorized_client" in text:
            print("YT_PREFLIGHT_REFRESH_INVALID_CLIENT (YT_CLIENT_ID/YT_CLIENT_SECRET passen nicht zum Token)")
        else:
            print("YT_PREFLIGHT_REFRESH_FAILED")
        return 1
    print("YT_PREFLIGHT_REFRESH_OK")
    try:
        granted = set(http_json("GET", "https://oauth2.googleapis.com/tokeninfo",
                                params={"access_token": token}).get("scope", "").split())
        print("Erteilte Berechtigungen: " + (", ".join(sorted(s.rsplit("/", 1)[-1] for s in granted)) or "keine"))
        missing = [s.rsplit("/", 1)[-1] for s in NEEDED if s not in granted]
        if missing:
            print("YT_PREFLIGHT_SCOPE_MISSING: " + ", ".join(missing))
    except Exception:
        print("Berechtigungen konnten nicht gelesen werden.")
    try:
        data = http_json("GET", "https://www.googleapis.com/youtube/v3/channels",
                         headers={"Authorization": f"Bearer {token}"},
                         params={"part": "snippet", "mine": "true"})
        items = data.get("items", [])
        seen = items[0].get("snippet", {}).get("customUrl", "?") if items else "kein Kanal"
        print(f"Kanal des Tokens: {seen} · erwartet: {expected_handle}")
        ok = youtube_is_channel(token, expected_handle)
        print("YT_PREFLIGHT_MATCH" if ok else "YT_PREFLIGHT_WRONG_CHANNEL")
        return 0 if ok else 1
    except Exception as exc:
        text = str(exc)
        if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in text or "insufficientPermissions" in text:
            print("YT_PREFLIGHT_CHANNEL_SCOPE_MISSING")
        else:
            m = re.search(r"HTTP (\d{3})", text)
            print("YT_PREFLIGHT_CHANNEL_CHECK_FAILED" + (f"_HTTP_{m.group(1)}" if m else ""))
        return 1
