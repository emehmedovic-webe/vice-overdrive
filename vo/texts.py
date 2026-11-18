"""Deutsche Texte pro Short: Hook, Titel, Beschreibung (YouTube) und Caption (TikTok).

Regelbasiert und kostenlos (kein bezahltes KI-API). Was im Brief steht, hat Vorrang.
YouTube und TikTok bekommen bewusst unterschiedliche Texte.
"""
from __future__ import annotations

import re

from . import allowlist

YT_TITLE_MAX = 100
TIKTOK_CAPTION_MAX = 2200

HOOK_TEMPLATES = [
    "Das hat in GTA 6 keiner kommen sehen 😳",
    "Warte bis zum Ende… 🔥",
    "So eskaliert Vice City in Sekunden",
]


def _tag(word: str) -> str:
    return "#" + re.sub(r"[^0-9A-Za-zÄÖÜäöüß]", "", word)


def _uniq(items):
    out = []
    for i in items:
        if i and i.lower() not in {o.lower() for o in out}:
            out.append(i)
    return out


def build_texts(brief: dict, cfg: dict) -> dict:
    tcfg = cfg["texts"]
    topic = brief.get("topic", "GTA 6").strip()
    hook = (brief.get("hook") or HOOK_TEMPLATES[sum(map(ord, topic)) % len(HOOK_TEMPLATES)]).strip()
    keywords = brief.get("keywords", [])
    credit = brief.get("credit", "").strip()
    streamer = allowlist.find(cfg, brief.get("streamer"))
    extra_tags = []
    if streamer:
        # Quellenangabe ist Pflicht: Streamer-Name + Kanal, plus Pflicht-Tags des Clipper-Programms.
        credit = allowlist.credit_line(streamer)
        extra_tags = [t if t.startswith(("#", "@")) else "#" + t for t in streamer.get("required_tags", [])]

    yt_tags = _uniq(extra_tags + tcfg["base_hashtags_youtube"] + [_tag(k) for k in keywords])[:max(6, len(extra_tags) + 3)]
    title = brief.get("title") or f"{topic}: {hook}"
    title = re.sub(r"\s+", " ", title).strip()
    suffix = " #Shorts"
    if len(title) + len(suffix) > YT_TITLE_MAX:
        title = title[: YT_TITLE_MAX - len(suffix) - 1].rstrip() + "…"
    title += suffix
    desc_lines = [hook, "", brief.get("description", f"{topic} – kurz und knapp auf Deutsch.")]
    if streamer:
        desc_lines += ["", f"🎥 Clip von {streamer['name']}: {allowlist.channel_url(streamer)}"]
    elif credit:
        desc_lines += ["", f"Material: {credit}"]
    desc_lines += ["", "Mehr GTA-6-Shorts: @viceoverdrive6", "", " ".join(yt_tags)]
    description = "\n".join(desc_lines)

    tt_tags = _uniq(extra_tags + tcfg["base_hashtags_tiktok"] + [_tag(k).lower() for k in keywords])[:max(8, len(extra_tags) + 4)]
    caption_core = brief.get("caption") or f"{hook} {topic} 👀 Was hättet ihr gemacht?"
    attribution = ""
    if streamer:
        attribution = f"\n🎥 Clip von {streamer['name']}: {allowlist.channel_url(streamer)}"
    elif credit:
        attribution = f" (Material: {credit})"
    caption_tail = attribution + "\n" + " ".join(tt_tags)
    remaining = TIKTOK_CAPTION_MAX - len(caption_tail)
    if remaining < 0:
        raise ValueError("TikTok-Quellenangabe und Hashtags überschreiten das Zeichenlimit.")
    caption = caption_core[:remaining].rstrip() + caption_tail

    texts = {
        "hook": hook,
        "credit": credit,
        "youtube": {"title": title, "description": description,
                    "tags": [t.lstrip("#") for t in yt_tags]},
        "tiktok": {"caption": caption, "hashtags": tt_tags},
    }
    validate_texts(texts)
    if streamer:
        url = allowlist.channel_url(streamer)
        assert url in texts["youtube"]["description"], "Quellenangabe fehlt in YouTube-Beschreibung"
        assert url in texts["tiktok"]["caption"], "Quellenangabe fehlt in TikTok-Caption"
    return texts


def validate_texts(texts: dict) -> None:
    yt, tt = texts["youtube"], texts["tiktok"]
    assert 0 < len(yt["title"]) <= YT_TITLE_MAX, "YouTube-Titel zu lang/leer"
    assert "<" not in yt["title"] and ">" not in yt["title"], "YouTube verbietet < > im Titel"
    assert len(tt["caption"]) <= TIKTOK_CAPTION_MAX, "TikTok-Caption zu lang"
    assert yt["description"].strip() != tt["caption"].strip(), "YouTube- und TikTok-Text müssen getrennt sein"
