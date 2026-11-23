"""Streamer-Allowlist: Nur Clips dieser Kanäle werden gesucht, geschnitten und gepostet.

Gepflegt in config.json unter clip_allowlist.streamers. Ein Eintrag braucht
twitch_login und name; active=false heißt nur vorgemerkt. proof ist der Beleg der
Freigabe (z. B. VOD-Link mit Zeitstempel der Ansage zum Clipper-Programm).
"""
from __future__ import annotations

import re


def streamers(cfg: dict, *, only_active: bool = True) -> list[dict]:
    items = cfg.get("clip_allowlist", {}).get("streamers", [])
    return [s for s in items if s.get("active", True) or not only_active]


def logins(cfg: dict) -> list[str]:
    return [s["twitch_login"].lower() for s in streamers(cfg)]


def find(cfg: dict, login: str | None) -> dict | None:
    if not login:
        return None
    login = login.lower().lstrip("@")
    return next((s for s in streamers(cfg, only_active=False) if s["twitch_login"].lower() == login), None)


def tiktok_handle(entry: dict) -> str:
    """@-Handle des Streamers für die Caption (config: tiktok_handle, sonst Twitch-Login)."""
    return "@" + (entry.get("tiktok_handle") or entry["twitch_login"]).lstrip("@").lower()


def channel_url(entry: dict) -> str:
    """Hauptkanal des Streamers; channel_url im Eintrag überschreibt Twitch (z. B. YouTube)."""
    return entry.get("channel_url") or f"https://www.twitch.tv/{entry['twitch_login'].lower()}"


def short_url(entry: dict) -> str:
    return channel_url(entry).split("://", 1)[-1].removeprefix("www.")


_PROOF_URL = re.compile(r"https://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:[/?#]\S*)?", re.IGNORECASE)


def has_proof(entry: dict, field: str = "proof") -> bool:
    """Ein Freigabebeleg muss nachprüfbar sein, nicht nur ein Freitext-Vermerk.

    Akzeptiert eine HTTPS-Quelle (z. B. VOD/Regeln/Clipper-Programm). Aussagen wie
    'mündlich bestätigt' bleiben als Notiz erhalten, schalten den Export aber nicht frei.
    """
    if field == "proof" and has_creator_confirmation(entry):
        return True
    proof = entry.get(field)
    if not isinstance(proof, str):
        return False
    # Ein echter Link mit Domain (https://seite.tld/...), nicht nur "https://" oder "https://x".
    return bool(_PROOF_URL.search(proof))


def has_creator_confirmation(entry: dict) -> bool:
    """Enis' dokumentierte Bestätigung (2026-11-23): Der Streamer sagt im Stream öffentlich,
    dass Clips erlaubt sind, solange nichts erfunden wird. Gilt nur mit Typ, Name und Datum
    und nur für Twitch-Clips (nicht für YouTube-Downloads)."""
    conf = entry.get("creator_confirmation")
    return (isinstance(conf, dict) and conf.get("type") == "verbal_stream_permission"
            and bool(str(conf.get("confirmed_by") or "").strip())
            and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(conf.get("date") or ""))))


def proof_problem(entry: dict | None, field: str = "proof") -> str | None:
    """Klartext-Grund, warum ein Streamer gesperrt ist (für die Export-Übersicht), sonst None."""
    if not entry:
        return "nicht in der Allowlist"
    if not entry.get("active", True):
        return "in der Allowlist pausiert"
    if not has_proof(entry, field):
        return "kein Freigabe-Beleg (Link oder dokumentierte Stream-Freigabe) in config.json"
    return None


def credit_line(entry: dict) -> str:
    """Quellenangabe, die in jede Beschreibung/Caption kommt."""
    return f"{entry['name']} – {short_url(entry)}"
