"""Deutsche Texte pro Short: Hook, Titel, Beschreibung (YouTube) und Caption (TikTok).

Regelbasiert und kostenlos (kein bezahltes KI-API). Was im Brief steht, hat Vorrang.
YouTube und TikTok bekommen bewusst unterschiedliche Texte.
"""
from __future__ import annotations

import re

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

    yt_tags = _uniq(tcfg["base_hashtags_youtube"] + [_tag(k) for k in keywords])[:6]
    title = brief.get("title") or f"{topic}: {hook}"
    title = re.sub(r"\s+", " ", title).strip()
    suffix = " #Shorts"
    if len(title) + len(suffix) > YT_TITLE_MAX:
        title = title[: YT_TITLE_MAX - len(suffix) - 1].rstrip() + "…"
    title += suffix
    desc_lines = [hook, "", brief.get("description", f"{topic} – kurz und knapp auf Deutsch.")]
    if credit:
        desc_lines += ["", f"Material: {credit}"]
    desc_lines += ["", "Mehr GTA-6-Shorts: @viceoverdrive6", "", " ".join(yt_tags)]
    description = "\n".join(desc_lines)

    tt_tags = _uniq(tcfg["base_hashtags_tiktok"] + [_tag(k).lower() for k in keywords])[:8]
    caption_core = brief.get("caption") or f"{hook} {topic} 👀 Was hättet ihr gemacht?"
    caption = f"{caption_core}"
    if credit:
        caption += f" (Material: {credit})"
    caption += "\n" + " ".join(tt_tags)
    caption = caption[:TIKTOK_CAPTION_MAX]

    texts = {
        "hook": hook,
        "youtube": {"title": title, "description": description,
                    "tags": [t.lstrip("#") for t in yt_tags]},
        "tiktok": {"caption": caption, "hashtags": tt_tags},
    }
    validate_texts(texts)
    return texts


def validate_texts(texts: dict) -> None:
    yt, tt = texts["youtube"], texts["tiktok"]
    assert 0 < len(yt["title"]) <= YT_TITLE_MAX, "YouTube-Titel zu lang/leer"
    assert "<" not in yt["title"] and ">" not in yt["title"], "YouTube verbietet < > im Titel"
    assert len(tt["caption"]) <= TIKTOK_CAPTION_MAX, "TikTok-Caption zu lang"
    assert yt["description"].strip() != tt["caption"].strip(), "YouTube- und TikTok-Text müssen getrennt sein"
