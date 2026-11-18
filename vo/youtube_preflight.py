from os import environ
import re
from .common import load_config
from .publish import youtube_access_token, youtube_is_channel

if not all(environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
    print("YT_PREFLIGHT_MISSING_SECRETS")
    raise SystemExit(0)
try:
    token = youtube_access_token()
except Exception as exc:
    if "invalid_grant" in str(exc):
        print("YT_PREFLIGHT_REFRESH_INVALID_GRANT")
    elif "invalid_client" in str(exc):
        print("YT_PREFLIGHT_REFRESH_INVALID_CLIENT")
    else:
        print("YT_PREFLIGHT_REFRESH_FAILED")
    raise SystemExit(0)
print("YT_PREFLIGHT_REFRESH_OK")
try:
    correct = youtube_is_channel(token, load_config()["youtube_channel"])
    print("YT_PREFLIGHT_MATCH" if correct else "YT_PREFLIGHT_WRONG_CHANNEL")
except Exception as exc:
    if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in str(exc) or "insufficientPermissions" in str(exc):
        print("YT_PREFLIGHT_CHANNEL_SCOPE_MISSING")
    else:
        match = re.search(r"HTTP (\d{3})", str(exc))
        print("YT_PREFLIGHT_CHANNEL_CHECK_FAILED" + (f"_HTTP_{match.group(1)}" if match else ""))
