# Instructions for Claude — VICE OVERDRIVE

Before changing, generating, approving, scheduling, or uploading any TikTok content, read and follow `docs/TIKTOK_CONTENT_SAFETY.md`. These are project requirements, not optional suggestions.

## Current TikTok incident — 2026-11-23

The creator shared screenshots from TikTok Account Check for `@viceoverdrive`. TikTok explicitly reported that the account itself had no problems or violations, but three individual posts were restricted from recommendation (“Kann nicht empfohlen werden”):

1. “Arbeit” — published 2026-11-18 at 7:24 PM.
2. “Überall steht Eris 👀 Was hättet ihr gemacht?” — published 2026-11-18 at 3:43 PM.
3. “GTA 6 First Ever Car Police Chase” — published 2026-11-18 at 3:41 PM.

The exact per-video restriction reasons were not opened in the screenshots and are unknown. Do not invent or infer a specific violation. This is not proof of an account-wide shadowban. The creator decided to replace/remove these three posts and publish new, carefully checked clips rather than appeal them for now. Do not delete or modify posts through automation; the creator handles account-side deletion manually.

## Mandatory behavior

- Review the complete rendered clip, captions, hashtags, audio, subtitles, overlays, and source context before it enters an upload queue.
- Verify source rights. A streamer clip is not automatically authorized because it is cropped, subtitled, or includes a facecam. If permission or another valid rights basis is unclear, stop and ask for human review.
- Reject or hold content that may violate TikTok Community Guidelines or be ineligible for recommendation. Do not claim a review guarantees approval or reach.
- Captions must be unique, accurate, and relevant to the individual clip. Use relevant hashtags only: `@streamer` plus 2–4 relevant hashtags (creator decision 2026-11-23, replaces the earlier `#fy`/`#fyp` request); never as an evasion tactic or reach guarantee.
- Never buy or use fake followers, likes, views, comments, bots, or engagement exchanges.
- If any check fails or confidence is insufficient, do not upload. Flag the exact reason for manual review.
- Do not bypass TikTok moderation or platform safeguards.
- Do not publish automatically without the creator's explicit authorization for the configured publishing flow.
- Do not change or remove the three restricted posts automatically. Do not state that their precise restriction reason is known unless the creator supplies the individual detail screen.

Video format (creator decision 2026-11-23, after TikTok flagged reframed clips as "Nicht originale Inhalte"): facecam top, gameplay bottom, own headline box, word-by-word subtitles of the exact spoken words, own comments only where true, supercar outro. See `vo/split_render.py` and `python -m vo compose`.

When making project changes, preserve existing work and inspect the current branch/status first. Do not overwrite parallel work.

## Clip-Suche (Enis 2026-11-25)

Zuerst VODs (`vod.yml`, letzte Streams mehrerer Tage), danach Twitch-Clips (`export.yml`). Prio 1 sind GTA-6-Momente, Prio 2 andere lustige Momente derselben Streamer (auch Nicht-GTA). Es gibt immer etwas Brauchbares: immer liefern statt „nichts gefunden“ zu melden. Der Inhaltsfilter (keine Nacktheit/Sexuelles) gilt weiter. Siehe `sourcing` in `config.json`.
