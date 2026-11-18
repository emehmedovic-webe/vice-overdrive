"""Streamer-Allowlist: Nur Clips dieser Kanäle werden gesucht, geschnitten und gepostet.

Gepflegt in config.json unter clip_allowlist.streamers. Ein Eintrag braucht
twitch_login und name; active=false heißt nur vorgemerkt. proof ist der Beleg der
Freigabe (z. B. VOD-Link mit Zeitstempel der Ansage zum Clipper-Programm).
"""
from __future__ import annotations


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


def channel_url(entry: dict) -> str:
    return f"https://www.twitch.tv/{entry['twitch_login'].lower()}"


def credit_line(entry: dict) -> str:
    """Quellenangabe, die in jede Beschreibung/Caption kommt."""
    return f"{entry['name']} – twitch.tv/{entry['twitch_login'].lower()}"
