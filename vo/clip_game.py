"""Spiel- und Hashtag-Schritt: Kategorien und beobachtete Themen statt Trend-Tags."""
from __future__ import annotations

import re

GAME_NAMES = {"gta5": "GTA V", "gta6": "GTA VI"}
TWITCH_GAME_NAMES = {"grand theft auto v": "gta5", "grand theft auto vi": "gta6"}
PATTERNS = {
    "gta5": re.compile(r"\b(?:gta|grand\W+theft\W+auto)[\s_-]*(?:v|5|online)\b", re.I),
    "gta6": re.compile(r"\b(?:gta|grand\W+theft\W+auto)[\s_-]*(?:vi|6)\b", re.I),
}
SCENE_TAGS = {
    "pursuit": "#Verfolgungsjagd",
    "stunt": "#GTAStunt",
    "crash": "#GTAFail",
    "roleplay": "#GTARP",
    "exploration": "#GTAEntdeckung",
    "other": "",
}


def explicit_games(text: str) -> set[str]:
    return {key for key, pattern in PATTERNS.items() if pattern.search(text)}


def youtube_game(snippet: dict) -> str | None:
    # Der Titel hat Vorrang. Tags/Beschreibung sind nur Zusatzsignale und können widersprechen.
    for text in (snippet.get("title", ""), " ".join(snippet.get("tags", [])),
                 snippet.get("description", "")[:500]):
        games = explicit_games(text)
        if games:
            return next(iter(games)) if len(games) == 1 else None
    return None


def clip_game(clip: dict, categories: dict) -> str | None:
    if clip.get("platform") == "twitch":
        category = next((name for name, game_id in categories.items() if game_id == clip.get("game_id")), "")
        game = TWITCH_GAME_NAMES.get(category.lower())
    else:
        game = clip.get("game")
    if game not in GAME_NAMES:
        return None
    indicated = explicit_games(clip.get("title") or "")
    return game if not indicated or indicated == {game} else None


def hashtags(game: str, scene: str, target: str) -> list[str]:
    game_tags = {"gta5": ["#GTAV", "#GrandTheftAutoV"],
                 "gta6": ["#GTAVI", "#GTA6"]}[game]
    scene_tag = SCENE_TAGS[scene]
    # RP ohne eindeutige Sichtbarkeit oder für GTA VI nicht als Genre versprechen.
    if scene == "roleplay" and game != "gta5":
        scene_tag = ""
    return (["#Shorts"] if target == "youtube" else []) + game_tags + (
        [scene_tag] if scene_tag else []) + ["#ViceOverdrive"]
