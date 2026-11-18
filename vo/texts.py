"""Deutsche Texte pro Short: Hook, Titel, Beschreibung (YouTube) und Caption (TikTok).

Regelbasiert und kostenlos (kein bezahltes KI-API). Was im Brief steht, hat Vorrang.
YouTube und TikTok bekommen bewusst unterschiedliche Texte.
"""
from __future__ import annotations

import re

from . import allowlist
from .clip_game import GAME_NAMES, hashtags

YT_TITLE_MAX = 100
TIKTOK_CAPTION_MAX = 2200
TIKTOK_HASHTAG_MAX = 5
TIKTOK_FIXED_TAGS = ("#fy", "#fyp")

# Nur belegbare Themen aus dem Clip-Titel oder einer bereits erkannten Szene ableiten.
_ANGLES = (
    (r"\b(?:radio|sender|funk|radiosender)\b", "radio", "#GTARadio"),
    (r"\b(?:verfolgungsjagd|polizeiflucht|polizeiverfolgung|(?:police|cop)\s+chase)\b", "pursuit", "#Verfolgungsjagd"),
    (r"\b(?:autodiebstahl|autoklau|grand theft auto for|steals? (?:a |an |the )?car)\b", "theft", "#GTAFahrzeuge"),
    (r"\b(?:aim|zielt|zielen|schuss|treffer)\b", "aim", "#GTAFail"),
    (r"\b(?:npc|npc[s]?|dialog|konter)\b", "dialog", "#GTANPC"),
    (r"\b(?:startet|erste[rsmn]?\s+(?:start|gameplay)|first (?:ever )?gameplay|spielt (?:zum )?ersten)\b", "launch", "#GTAGameplay"),
    (r"\b(?:fahrt|fährt|driving|am steuer|lenkrad)\b", "drive", "#GTAFahrzeuge"),
    (r"\b(?:grafik|optik|graphics|sieht .* aus)\b", "look", "#GTADetails"),
)
_COPY = {
    "radio": (
        "„{topic}“. Hier lohnt sich das Zuhören: {who} hat in {game} einen Radio-Moment erwischt, der für sich schon einen eigenen Clip verdient.",
        "Bei „{topic}“ läuft das Radio nicht nur nebenbei. Der Ausschnitt von {who} zeigt, wie gut ein kurzer Funkmoment in {game} für sich stehen kann.",
    ),
    "pursuit": (
        "Für {who} steht in {game} die Polizei im Mittelpunkt. „{topic}“ ist der kurze Ausschnitt aus der Verfolgung, direkt aus dem Stream geschnitten.",
        "„{topic}“ bringt die Verfolgung von {who} auf den Punkt. Der Clip bleibt bei diesem einen Moment aus {game} und lässt den Rest des Streams außen vor.",
    ),
    "theft": (
        "„{topic}“ ist der Moment, in dem der Spieltitel für {who} Programm wird. Der Ausschnitt zeigt genau den Autodiebstahl aus der Session in {game}.",
        "Hier ist der Autoklau aus dem Stream von {who}. Unter „{topic}“ landet der Moment direkt als kurzer Ausschnitt aus der Session in {game}.",
    ),
    "aim": (
        "„{topic}“ rückt bei {who} ausgerechnet das Zielen in den Mittelpunkt. Der kurze Ausschnitt aus {game} bleibt bei diesem Moment statt bei der ganzen Mission.",
        "In diesem Ausschnitt aus {game} geht es bei {who} ums Aim. „{topic}“ fasst den Moment zusammen, der aus dem Stream einzeln herausgeschnitten wurde.",
    ),
    "dialog": (
        "„{topic}“ rückt das Gespräch in den Vordergrund. In diesem kurzen Ausschnitt aus {game} lohnt es sich, bei {who} besonders auf den Dialog zu achten.",
        "Der Moment von {who} braucht keine lange Vorgeschichte. „{topic}“ legt den Fokus auf den Dialog, der in diesem kurzen Ausschnitt aus {game} auffällt.",
    ),
    "launch": (
        "„{topic}“ hält den Einstieg von {who} in {game} fest. Wer nicht die ganze Session gesehen hat, bekommt hier einen kurzen Eindruck direkt aus dem Stream.",
        "Ein früher Blick auf {game} mit {who}. Der Ausschnitt „{topic}“ bleibt beim Einstieg ins Spiel und holt genau diesen Moment aus dem längeren Stream.",
    ),
    "drive": (
        "Bei „{topic}“ gehört der Ausschnitt {who} am Steuer. Der Clip bleibt ganz bei der Fahrt und zeigt einen kurzen Moment aus der Session in {game}.",
        "Eine Fahrt mit {who} in {game}, festgehalten unter „{topic}“. In diesem Ausschnitt steht das Fahren selbst im Mittelpunkt, direkt aus der Perspektive des Streams.",
    ),
    "look": (
        "„{topic}“ richtet den Blick auf die Optik von {game}. Der Ausschnitt kommt aus dem Stream von {who} und lässt den visuellen Eindruck für sich sprechen.",
        "Bei „{topic}“ geht es um den ersten Blick auf {game}. Ein kurzer Ausschnitt aus dem Stream von {who}, bei dem sich genaueres Hinschauen lohnt.",
    ),
    "other": (
        "„{topic}“ ist ein kurzer Moment aus {game} bei {who}. Er steht auch ohne die ganze Session für sich und kommt direkt aus dem Stream.",
        "Wer den Stream von {who} verpasst hat, bekommt hier „{topic}“ als eigenen Ausschnitt. Dieser Clip hält den Moment aus {game} fest, ohne den ganzen Verlauf mitzunehmen.",
        "Ein einzelner Moment aus {game}: „{topic}“. Der Ausschnitt stammt von {who} und greift genau den Teil des Streams heraus, den der Clip-Titel ankündigt.",
        "Hier gibt es „{topic}“ aus der Session von {who} in {game}. Der kurze Ausschnitt bleibt bei diesem Moment und braucht dafür keine lange Einleitung.",
    ),
}

HOOK_TEMPLATES = [
    "Das hat in GTA 6 keiner kommen sehen 😳",
    "Warte bis zum Ende… 🔥",
    "So eskaliert Vice City in Sekunden",
]


def _tag(word: str) -> str:
    clean = re.sub(r"[^0-9A-Za-zÄÖÜäöüß]", "", word)
    return "#" + clean if clean else ""


def _uniq(items):
    out = []
    for i in items:
        if i and i.lower() not in {o.lower() for o in out}:
            out.append(i)
    return out


def _caption_from_topic(topic: str, game: str | None, who: str, scene: str) -> tuple[str, str]:
    label = re.sub(r"https?://\S+|(?<!\w)[#@]\w+", "", topic)
    label = " ".join(label.split()[:8])[:100].strip(" \t.!?…")
    label = label or "GTA-Clipausschnitt"
    angle, tag = next(((angle, tag) for pattern, angle, tag in _ANGLES
                       if re.search(pattern, topic, re.IGNORECASE)), ("other", "#GTAClips"))
    if scene == "pursuit":
        angle, tag = "pursuit", "#Verfolgungsjagd"
    variants = _COPY[angle]
    idx = sum((i + 1) * ord(c) for i, c in enumerate(topic.casefold())) % len(variants)
    parts = label.split()
    rendered = variants[idx].format(topic=label, game=GAME_NAMES.get(game, "GTA"), who=who)
    while len(rendered.split()) > 30 and len(parts) > 1:
        parts.pop()
        rendered = variants[idx].format(topic=" ".join(parts) + "…", game=GAME_NAMES.get(game, "GTA"), who=who)
    return rendered, tag


def tiktok_description(brief: dict, cfg: dict) -> str:
    """Reine Beschreibung (ohne Quelle/Hashtags), aus der build_texts die TikTok-Caption baut."""
    streamer = allowlist.find(cfg, brief.get("streamer"))
    generated, _ = _caption_from_topic(brief.get("topic", "GTA 6").strip(), brief.get("game"),
                                       streamer["name"] if streamer else "dem Creator", brief.get("scene", "other"))
    return (brief.get("caption") or generated).strip()


def _tiktok_hashtags(candidates: list[str]) -> list[str]:
    fixed = set(TIKTOK_FIXED_TAGS)
    tags = [t for t in _uniq(h if h.startswith("#") else "#" + h
                            for h in candidates if h and not h.startswith("@"))
            if re.fullmatch(r"#\w+", t) and t.casefold() not in fixed]
    return tags[:TIKTOK_HASHTAG_MAX - len(TIKTOK_FIXED_TAGS)] + list(TIKTOK_FIXED_TAGS)


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

    game = brief.get("game")
    yt_base, tt_base = tcfg["base_hashtags_youtube"], tcfg["base_hashtags_tiktok"]
    scene = brief.get("scene", "other")
    generated, topic_tag = _caption_from_topic(
        topic, game, streamer["name"] if streamer else "dem Creator", scene)
    caption_core = (brief.get("caption") or generated).strip()
    if game in GAME_NAMES:
        yt_base = hashtags(game, scene, "youtube")
        scene_tags = hashtags(game, scene, "tiktok")[2:-1]
        tt_base = ["#GTAV" if game == "gta5" else "#GTA6", *scene_tags, topic_tag,
                   _tag(streamer["name"]) if streamer else "", "#GTAGameplay", "#TwitchClips", "#ViceOverdrive"]
    creator_tag = _tag(streamer["name"]) if streamer else ""
    yt_tags = _uniq(extra_tags + yt_base + [topic_tag, creator_tag] + [_tag(k) for k in keywords]
                   + ["#GTAGameplay", "#GamingClips", "#GameplayHighlights", "#ViceOverdrive"])[:max(8, len(extra_tags) + 4)]
    title = brief.get("title") or f"{topic}: {hook}"
    title = re.sub(r"\s+", " ", title).strip()
    suffix = " #Shorts"
    if len(title) + len(suffix) > YT_TITLE_MAX:
        title = title[: YT_TITLE_MAX - len(suffix) - 1].rstrip() + "…"
    title += suffix
    provided = (brief.get("description") or "").strip()
    if provided.split("\n", 1)[0].strip().casefold() == hook.casefold():
        provided = provided.partition("\n")[2].strip()
    if not provided or provided.startswith("Originalclip:") or provided.casefold() == topic.casefold():
        provided = "\n\n".join(x for x in (generated, provided if provided.startswith("Originalclip:") else "") if x)
    desc_lines = [provided]
    if streamer:
        desc_lines += ["", f"🎥 Clip von {streamer['name']}: {allowlist.channel_url(streamer)}"]
    elif credit:
        desc_lines += ["", f"Material: {credit}"]
    desc_lines += ["", " ".join(yt_tags)]
    description = "\n".join(desc_lines)

    if sum(t.startswith("#") and t.casefold() not in TIKTOK_FIXED_TAGS
           for t in _uniq(extra_tags)) > TIKTOK_HASHTAG_MAX - len(TIKTOK_FIXED_TAGS):
        raise ValueError("TikTok-Limit: Die Pflicht-Tags passen nicht zusammen mit #fy und #fyp.")
    tt_tags = _tiktok_hashtags(extra_tags + tt_base[:1] + [creator_tag] + tt_base +
                               [_tag(k).lower() for k in keywords])
    tt_tags += [t for t in _uniq(extra_tags) if t.startswith("@")]
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


# Was nie in einer selbst geposteten TikTok-Caption landen darf: Links, Quellen-/Credit-Zeilen,
# Standardfragen, Notizen an Enis (Alternativen, Bewertungen, Überschriften).
_CAPTION_EXTRAS = (
    (r"https?://|www\.|\b[\w-]+\.(?:tv|com|de|net|gg)/", "URL"),
    (r"clip von|quelle|originalclip|material:|credit|🎥", "Quellen-/Credit-Zeile"),
    (r"was hättet ihr|was meint ihr|was sagt ihr|schreibt.*kommentar|👀", "Standardfrage"),
    (r"alternative|\bpasst\b|hinweis|anmerkung|überschrift|caption|hashtags?:", "Notiz statt Caption"),
)


def _sentences(text: str) -> list[str]:
    return [s.strip(" .!?…").casefold() for s in re.split(r"(?<=[.!?…])\s+", text) if s.strip(" .!?…")]


def tiktok_caption_problems(caption: str) -> list[str]:
    """Prüft das Format: Beschreibung, eine Leerzeile, eine Zeile nur mit 1–5 Hashtags. Sonst nichts."""
    problems = []
    blocks = caption.strip().split("\n\n")
    if len(blocks) != 2 or "\n" in blocks[0].strip() or "\n" in blocks[1].strip():
        return ["Caption muss genau aus Beschreibung, Leerzeile und einer Hashtag-Zeile bestehen."]
    desc, tags = blocks[0].strip(), blocks[1].strip().split()
    if not desc or "#" in desc or "@" in desc:
        problems.append("Beschreibung fehlt oder enthält Hashtags/Handles.")
    if not 0 < len(tags) <= TIKTOK_HASHTAG_MAX or not all(re.fullmatch(r"#\w+", t) for t in tags):
        problems.append(f"Hashtag-Zeile muss 1–{TIKTOK_HASHTAG_MAX} Hashtags und sonst nichts enthalten.")
    if not set(TIKTOK_FIXED_TAGS).issubset(t.casefold() for t in tags):
        problems.append("TikTok-Caption braucht #fy und #fyp.")
    if len({t.casefold() for t in tags}) != len(tags):
        problems.append("Doppelte Hashtags.")
    for pattern, label in _CAPTION_EXTRAS:
        if re.search(pattern, caption, re.IGNORECASE):
            problems.append(f"Unerlaubter Zusatz: {label}.")
    sents = _sentences(desc)
    if len(set(sents)) != len(sents):
        problems.append("Doppelter Text in der Beschreibung.")
    words = desc.split()
    half = len(words) // 2
    if half >= 3 and words[:half] == words[half:2 * half]:
        problems.append("Doppelter Text in der Beschreibung.")
    if len(caption) > TIKTOK_CAPTION_MAX:
        problems.append("Caption zu lang.")
    return problems


def tiktok_export_caption(description: str, hashtags: list[str]) -> str:
    """Caption zum Selbstposten: nur Beschreibung + eine Hashtag-Zeile. Quelle bleibt intern."""
    desc = re.sub(r"https?://\S+", "", description)
    desc = " ".join(line.strip() for line in desc.splitlines()
                    if line.strip() and not re.search(r"clip von|originalclip|quelle|material:|🎥", line, re.I))
    desc = re.sub(r"(?<!\w)[#@]\w+", "", desc)
    desc = re.sub(r"\s*👀?\s*was hättet ihr gemacht\?", "", desc, flags=re.I)
    desc = " ".join(desc.split())
    unique: list[str] = []
    for s in re.split(r"(?<=[.!?…])\s+", desc):
        if s and s.strip(" .!?…").casefold() not in {u.strip(" .!?…").casefold() for u in unique}:
            unique.append(s)
    desc = " ".join(unique)
    tags = _tiktok_hashtags(hashtags)
    caption = f"{desc}\n\n{' '.join(tags)}"
    problems = tiktok_caption_problems(caption)
    if problems:
        raise ValueError(" ".join(problems))
    return caption


def validate_texts(texts: dict) -> None:
    yt, tt = texts["youtube"], texts["tiktok"]
    assert 0 < len(yt["title"]) <= YT_TITLE_MAX, "YouTube-Titel zu lang/leer"
    assert "<" not in yt["title"] and ">" not in yt["title"], "YouTube verbietet < > im Titel"
    assert len(tt["caption"]) <= TIKTOK_CAPTION_MAX, "TikTok-Caption zu lang"
    assert yt["description"].strip() != tt["caption"].strip(), "YouTube- und TikTok-Text müssen getrennt sein"
