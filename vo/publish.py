"""Veröffentlichung: YouTube (offizielle Data API v3) und TikTok (offizielle Content Posting API).

Standard ist IMMER Dry-Run. Live nur mit --live UND gesammelter Freigabe
(approved: true im Freigabe-Batch). Synthetische Tests werden auch live hart blockiert.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from .common import http_json, iso, now_utc, read_json, secret, write_json

YT_TOKEN_URL = "https://oauth2.googleapis.com/token"
YT_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"



def load_short(short_dir: Path) -> dict:
    return read_json(short_dir / "manifest.json", None)


def blocked_reason(manifest: dict, target: str, approval: dict | None) -> str | None:
    if manifest.get("synthetic") or manifest.get("rights", {}).get("type") == "synthetic":
        return "synthetisches Testvideo – wird nie veröffentlicht"
    if manifest.get("rights", {}).get("type") not in {"own", "licensed"}:
        return "Rechte nicht bestätigt"
    if not approval or not approval.get(target, {}).get("approved"):
        return "nicht freigegeben"
    if manifest.get("published", {}).get(target):
        return "bereits veröffentlicht"
    return None


# ---------- Freigabe-Batch ----------

def make_batch(shorts_root: Path, approvals_dir: Path) -> Path:
    items = []
    for mf in sorted(shorts_root.glob("*/manifest.json")):
        m = json.loads(mf.read_text(encoding="utf-8"))
        if m.get("published", {}).get("youtube") and m.get("published", {}).get("tiktok"):
            continue
        items.append({
            "short_id": m["short_id"],
            "synthetic": bool(m.get("synthetic")),
            "youtube_title": m["texts"]["youtube"]["title"],
            "tiktok_caption": m["texts"]["tiktok"]["caption"],
            "youtube": {"approved": False},
            "tiktok": {"approved": False},
        })
    path = approvals_dir / f"batch-{now_utc().strftime('%Y%m%d-%H%M')}.json"
    write_json(path, {"created_at": iso(now_utc()),
                      "anleitung": "Pro Short und Plattform approved auf true setzen, dann publish starten.",
                      "items": items})
    return path


def latest_approvals(approvals_dir: Path) -> dict:
    batches = sorted(approvals_dir.glob("batch-*.json"))
    if not batches:
        return {}
    data = json.loads(batches[-1].read_text(encoding="utf-8"))
    return {i["short_id"]: i for i in data["items"]}


# ---------- YouTube ----------

def youtube_body(m: dict, cfg: dict) -> dict:
    y, t = cfg["youtube"], m["texts"]["youtube"]
    return {
        "snippet": {"title": t["title"], "description": t["description"], "tags": t["tags"],
                    "categoryId": y["category_id"], "defaultLanguage": y["default_language"],
                    "defaultAudioLanguage": y["default_language"]},
        "status": {"privacyStatus": y["privacy_status"], "selfDeclaredMadeForKids": y["made_for_kids"],
                   "containsSyntheticMedia": False},
    }


def youtube_access_token() -> str:
    data = http_json("POST", YT_TOKEN_URL, form={
        "client_id": secret("YT_CLIENT_ID"), "client_secret": secret("YT_CLIENT_SECRET"),
        "refresh_token": secret("YT_REFRESH_TOKEN"), "grant_type": "refresh_token"})
    return data["access_token"]


def youtube_upload(video: Path, body: dict, token: str) -> str:
    size = video.stat().st_size
    init = urllib.request.Request(
        f"{YT_UPLOAD_URL}?uploadType=resumable&part=snippet,status", method="POST",
        data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    with urllib.request.urlopen(init, timeout=60) as resp:
        location = resp.headers["Location"]
    with video.open("rb") as fh:
        put = urllib.request.Request(location, method="PUT", data=fh.read(),
                                     headers={"Content-Type": "video/mp4"})
        with urllib.request.urlopen(put, timeout=600) as resp:
            return json.loads(resp.read())["id"]


# ---------- TikTok direkt (Content Posting API, kostenlos) ----------
# Modus "inbox": Video landet als Entwurf/Benachrichtigung in der TikTok-App,
#                 dort selbst fertig posten (Scope video.upload).
# Modus "direct": Direct Post (Scope video.publish). Solange die App nicht von
#                 TikTok geprüft ist, nur SELF_ONLY und nur bei PRIVATEM Konto.

TT_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TT_API = "https://open.tiktokapis.com/v2/post/publish"
TT_MAX_SINGLE_CHUNK = 64 * 1024 * 1024


def tiktok_init_body(m: dict, cfg: dict, video_size: int, creator: dict | None = None) -> dict:
    t = cfg["tiktok"]
    source = {"source": "FILE_UPLOAD", "video_size": video_size,
              "chunk_size": video_size, "total_chunk_count": 1}
    if t["mode"] == "inbox":
        return {"source_info": source}
    privacy = t["privacy_level"]
    if creator and privacy not in creator.get("privacy_level_options", []):
        raise RuntimeError(f"privacy_level {privacy} nicht erlaubt, TikTok bietet: {creator.get('privacy_level_options')}")
    return {"post_info": {"title": m["texts"]["tiktok"]["caption"], "privacy_level": privacy,
                          "disable_comment": False, "disable_duet": False, "disable_stitch": False,
                          "video_cover_timestamp_ms": 1500, "brand_content_toggle": False,
                          "brand_organic_toggle": False, "is_aigc": False},
            "source_info": source}


def tiktok_endpoint(cfg: dict) -> str:
    return f"{TT_API}/inbox/video/init/" if cfg["tiktok"]["mode"] == "inbox" else f"{TT_API}/video/init/"


def tiktok_access_token() -> str:
    data = http_json("POST", TT_TOKEN_URL, form={
        "client_key": secret("TIKTOK_CLIENT_KEY"), "client_secret": secret("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": secret("TIKTOK_REFRESH_TOKEN")})
    if "access_token" not in data:
        raise RuntimeError(f"TikTok-Token fehlgeschlagen: {data.get('error')} {data.get('error_description')}")
    if data.get("refresh_token") and data["refresh_token"] != os.environ.get("TIKTOK_REFRESH_TOKEN"):
        print("HINWEIS: TikTok hat einen neuen Refresh-Token ausgegeben. Secret TIKTOK_REFRESH_TOKEN "
              "bei Gelegenheit über die Verbinden-Seite erneuern (gilt 365 Tage).")
    return data["access_token"]


def tiktok_check() -> dict:
    """Echte Anmeldeprüfung ohne Upload: Refresh-Grant, user/info, creator_info.

    Gibt keine Token aus. Meldet nur, ob TikTok einen neuen Refresh-Token ausgegeben hat.
    """
    key = secret("TIKTOK_CLIENT_KEY")
    if not key.startswith("sb"):
        raise SystemExit("TIKTOK_CLIENT_KEY ist kein Sandbox-Key (erwartet Präfix 'sb'). Abbruch.")
    old = secret("TIKTOK_REFRESH_TOKEN")
    data = http_json("POST", TT_TOKEN_URL, form={
        "client_key": key, "client_secret": secret("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": old})
    if "access_token" not in data:
        raise SystemExit(f"TikTok-Token fehlgeschlagen: {data.get('error')} {data.get('error_description')}")
    token = data["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    info = http_json("GET", "https://open.tiktokapis.com/v2/user/info/", headers=auth,
                     params={"fields": "open_id,display_name"})
    creator = _tt_call("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", token, {})
    return {
        "scope": data.get("scope", ""),
        "display_name": info.get("data", {}).get("user", {}).get("display_name"),
        "creator_username": creator.get("creator_username"),
        "privacy_level_options": creator.get("privacy_level_options"),
        "refresh_token_rotated": bool(data.get("refresh_token")) and data["refresh_token"] != old,
    }


def tiktok_revoke_stored() -> str:
    """Widerruft den im Secret gespeicherten (alten) Zugang über TikToks offiziellen Revoke.

    Nur auf ausdrücklichen Wunsch. Gibt keine Token aus.
    """
    key, sec = secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET")
    data = http_json("POST", TT_TOKEN_URL, form={
        "client_key": key, "client_secret": sec,
        "grant_type": "refresh_token", "refresh_token": secret("TIKTOK_REFRESH_TOKEN")})
    if "access_token" not in data:
        return f"Alter Token ist bereits nicht mehr nutzbar ({data.get('error')}). Nichts zu widerrufen."
    res = http_json("POST", "https://open.tiktokapis.com/v2/oauth/revoke/", form={
        "client_key": key, "client_secret": sec, "token": data["access_token"]})
    if res.get("error"):
        raise SystemExit(f"Widerruf fehlgeschlagen: {res.get('error')} {res.get('error_description')}")
    after = http_json("POST", TT_TOKEN_URL, form={
        "client_key": key, "client_secret": sec,
        "grant_type": "refresh_token", "refresh_token": secret("TIKTOK_REFRESH_TOKEN")})
    if "access_token" in after:
        raise SystemExit("Widerruf gemeldet, aber der alte Refresh-Token funktioniert noch.")
    return f"Widerrufen. Gegenprobe: alter Refresh-Token wird abgelehnt ({after.get('error')})."


def _tt_call(path_or_url: str, token: str, body: dict) -> dict:
    url = path_or_url if path_or_url.startswith("https://") else f"{TT_API}/{path_or_url}"
    data = http_json("POST", url, headers={"Authorization": f"Bearer {token}",
                                            "Content-Type": "application/json; charset=UTF-8"}, body=body)
    err = data.get("error", {})
    if err.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok-Fehler {err.get('code')}: {err.get('message')} (log_id {err.get('log_id')})")
    return data.get("data", {})


def tiktok_upload(video: Path, m: dict, cfg: dict, token: str) -> dict:
    size = video.stat().st_size
    if size > TT_MAX_SINGLE_CHUNK:
        raise RuntimeError("Video größer als 64 MB – Shorts sollten deutlich kleiner sein.")
    creator = None
    if cfg["tiktok"]["mode"] == "direct":
        creator = _tt_call("creator_info/query/", token, {})
        if m["video"]["duration"] > creator.get("max_video_post_duration_sec", 600):
            raise RuntimeError("Video ist länger, als TikTok für dieses Konto erlaubt.")
    init = _tt_call(tiktok_endpoint(cfg), token, tiktok_init_body(m, cfg, size, creator))
    put = urllib.request.Request(init["upload_url"], method="PUT", data=video.read_bytes(), headers={
        "Content-Type": "video/mp4", "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size - 1}/{size}"})
    with urllib.request.urlopen(put, timeout=600):
        pass
    status = _tt_call("status/fetch/", token, {"publish_id": init["publish_id"]})
    return {"publish_id": init["publish_id"], "status": status.get("status"), "mode": cfg["tiktok"]["mode"]}


# ---------- Ablauf ----------

def publish(target: str, shorts_root: Path, approvals_dir: Path, log_dir: Path, cfg: dict,
            live: bool = False) -> list[dict]:
    approvals = latest_approvals(approvals_dir)
    results = []
    token = None
    for mf in sorted(shorts_root.glob("*/manifest.json")):
        m = json.loads(mf.read_text(encoding="utf-8"))
        reason = blocked_reason(m, target, approvals.get(m["short_id"]))
        if target == "youtube":
            payload = youtube_body(m, cfg)
        else:
            video = mf.parent / m["file"]
            size = video.stat().st_size if video.exists() else 0
            payload = {"endpoint": tiktok_endpoint(cfg), "body": tiktok_init_body(m, cfg, size)}
        entry = {"short_id": m["short_id"], "target": target, "mode": "live" if live else "dry-run",
                 "blocked": reason, "payload": payload}
        if live and not reason:
            if target == "youtube":
                token = token or youtube_access_token()
                vid = youtube_upload(mf.parent / m["file"], payload, token)
                m.setdefault("published", {})["youtube"] = {"video_id": vid, "at": iso(now_utc())}
            else:
                token = tiktok_access_token()
                res = tiktok_upload(mf.parent / m["file"], m, cfg, token)
                m.setdefault("published", {})["tiktok"] = {**res, "at": iso(now_utc())}
            write_json(mf, m)
            entry["result"] = m["published"][target]
        results.append(entry)
    write_json(log_dir / f"publish-{target}-{'live' if live else 'dryrun'}-{now_utc().strftime('%Y%m%d-%H%M%S')}.json",
               results)
    return results
