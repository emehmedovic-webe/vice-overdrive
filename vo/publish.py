"""Veröffentlichung: YouTube (offizielle Data API v3) und TikTok (über Buffer).

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
BUFFER_URL = "https://api.buffer.com"

CREATE_POST = """mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id text } }
    ... on MutationError { message }
  }
}"""


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


# ---------- TikTok über Buffer ----------

def buffer_input(m: dict, cfg: dict, channel_id: str) -> dict:
    url = m.get("public_video_url") or (
        os.environ.get("VO_MEDIA_BASE_URL", "").rstrip("/") + f"/{m['short_id']}.mp4"
        if os.environ.get("VO_MEDIA_BASE_URL") else None)
    if not url:
        url = "https://BEISPIEL.invalid/fehlt-noch-oeffentliche-video-url.mp4"
    b = cfg["buffer"]
    return {"channelId": channel_id, "text": m["texts"]["tiktok"]["caption"],
            "schedulingType": b["scheduling_type"], "mode": b["mode"], "needsApproval": False,
            "assets": [{"video": {"url": url, "metadata": {"thumbnailOffset": 1500}}}],
            "metadata": {"tiktok": {"isAiGenerated": False}}}


def buffer_create(input_: dict) -> dict:
    data = http_json("POST", BUFFER_URL, headers={"Authorization": f"Bearer {secret('BUFFER_API_KEY')}"},
                     body={"query": CREATE_POST, "variables": {"input": input_}})
    if data.get("errors"):
        raise RuntimeError(f"Buffer-Fehler: {data['errors']}")
    res = data["data"]["createPost"]
    if res.get("message"):
        raise RuntimeError(f"Buffer-Fehler: {res['message']}")
    return res["post"]


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
            payload = buffer_input(m, cfg, os.environ.get("BUFFER_TIKTOK_CHANNEL_ID", "<BUFFER_TIKTOK_CHANNEL_ID>"))
        entry = {"short_id": m["short_id"], "target": target, "mode": "live" if live else "dry-run",
                 "blocked": reason, "payload": payload}
        if live and not reason:
            if target == "youtube":
                token = token or youtube_access_token()
                vid = youtube_upload(mf.parent / m["file"], payload, token)
                m.setdefault("published", {})["youtube"] = {"video_id": vid, "at": iso(now_utc())}
            else:
                if "BEISPIEL.invalid" in payload["assets"][0]["video"]["url"]:
                    raise SystemExit("Für Buffer fehlt eine öffentlich abrufbare Video-URL (VO_MEDIA_BASE_URL).")
                payload["channelId"] = secret("BUFFER_TIKTOK_CHANNEL_ID")
                post = buffer_create(payload)
                m.setdefault("published", {})["tiktok"] = {"buffer_post_id": post["id"], "at": iso(now_utc())}
            write_json(mf, m)
            entry["result"] = m["published"][target]
        results.append(entry)
    write_json(log_dir / f"publish-{target}-{'live' if live else 'dryrun'}-{now_utc().strftime('%Y%m%d-%H%M%S')}.json",
               results)
    return results
