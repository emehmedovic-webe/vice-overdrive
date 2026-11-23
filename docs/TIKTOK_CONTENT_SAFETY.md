# TikTok Content Safety & Publishing Rules

These rules apply to every VICE OVERDRIVE TikTok clip, caption, hashtag set, and scheduled upload.

## Publishing principle

Only publish content that has passed the checks below. The goal is to reduce Community Guidelines violations and recommendation-ineligibility risks. No checklist can guarantee that TikTok will approve or recommend a post; TikTok makes the final decision.

## 1. Clip review

Before scheduling or uploading, review the complete video, including the opening, ending, overlays, subtitles, audio, streamer facecam, chat, and any embedded footage.

- Reject clips that contain content that appears to violate TikTok's Community Guidelines.
- Pay particular attention to graphic or glorified violence, threats, harassment, hateful conduct, sexual content, dangerous acts, and other restricted material. Context matters; do not assume that all fictional gameplay violence is automatically prohibited.
- Do not use misleading edits, deceptive hooks, fake claims, or captions that misrepresent what happens in the clip.
- Do not publish a clip if its source, context, or rights status cannot be established.
- Do not assume that cropping, subtitles, a reaction facecam, or other minor edits make someone else's footage authorized or sufficiently original.
- The vertical renderer must preserve the complete source frame proportionally (fit/letterbox over a blurred background); do not center-crop landscape footage in a way that can remove the streamer facecam.
- A clipper-program allowlist entry is not approved by a free-text note such as 'verbally confirmed'. The proof field must contain a verifiable HTTPS reference to the applicable VOD timestamp, program rules, or permission. Until then, automated clip processing must hold that streamer.
- Exception decided by the creator on 2026-11-23: for montanablack88, eligella, xrohat and trymacs, the creator confirmed that these streamers say publicly in their streams that clips are fine as long as nothing is made up. This is recorded per streamer as `creator_confirmation` (type `verbal_stream_permission`, confirmed_by, date) in `config.json` and counts as the rights basis for Twitch clips only (not for YouTube downloads). Because of that condition, captions, hooks and subtitles must never invent or exaggerate anything; every other check in this document still applies.
- Prefer original gameplay, commentary, analysis, or substantial creative contribution. Obtain and document permission or another valid rights basis before using third-party streamer footage.
- Check music and other audio separately for usage rights.

## 2. Caption and hashtag review

- Write a distinct caption that accurately describes the individual clip.
- Avoid spam, repeated boilerplate, misleading engagement bait, and irrelevant hashtags.
- Use only relevant hashtags. Creator decision 2026-11-23: caption = one accurate sentence, blank line, then `@streamer` and 2–4 relevant hashtags (`#gta6 #<streamer>` + one topic tag). No #fyp/#fy/#viral. Hashtags never bypass moderation or guarantee reach.
- Do not claim that a clip is official, exclusive, leaked, or confirmed unless that is demonstrably true.

## 3. Pre-publish checklist

A clip may proceed only after a human or automated review has checked:

- [ ] Full video reviewed, including overlays, audio, subtitles, and ending.
- [ ] Streamer facecam/person is clearly visible and not cropped out; the full source frame was preserved.
- [ ] No apparent Community Guidelines violation.
- [ ] Source and usage rights checked; third-party footage has an adequate rights basis.
- [ ] Caption is accurate, original, and specific to this clip.
- [ ] Hashtags are relevant and not misleading.
- [ ] No obvious spam, deceptive claims, or engagement manipulation.
- [ ] Any uncertainty is flagged for human review rather than auto-published.

If any check fails or is uncertain, hold the clip. Do not auto-publish it.

## 4. Existing restricted posts and account status

On 2026-11-23, the creator shared TikTok Account Check screenshots for @viceoverdrive. TikTok stated: “Dein Konto hat keine Probleme oder Verstöße, aber einige deiner Beiträge sind eingeschränkt. Neue Beiträge werden nicht eingeschränkt, solange sie unseren Community-Richtlinien folgen.” The screen listed exactly three posts as “Kann nicht empfohlen werden”:

1. “Arbeit” — published 2026-11-18 at 7:24 PM.
2. “Überall steht Eris 👀 Was hättet ihr gemacht?” — published 2026-11-18 at 3:43 PM.
3. “GTA 6 First Ever Car Police Chase” — published 2026-11-18 at 3:41 PM.

The screenshot did not show the individual restriction reasons. Do not guess why these posts were restricted. The creator chose to replace/remove these three posts and publish new, carefully reviewed clips instead of appealing them for now. This is an individual-post recommendation restriction, not evidence of an account-wide shadowban.

- Do not automatically delete posts or alter the live account. The creator handles removal manually.
- Keep a record of the restriction reason if it is available before removal, so the same issue can be avoided in future clips.
- TikTok's account check showed that the account itself had no account-level problems or violations at the time of the screenshot, while three individual posts were restricted from recommendation. Do not describe this as a confirmed account-wide shadowban.

## 5. Fake engagement

- Never buy followers, likes, views, comments, or other engagement.
- Never use bots, engagement exchanges, or artificial activity.
- Do not promise that a clean review, a hashtag, or a posting schedule will guarantee views or For You distribution.

## 6. Automation behavior

- Run the content checks before an upload is queued.
- If a check fails, rights are unclear, or the system cannot confidently assess the clip, mark it for manual review and stop the upload.
- Do not bypass TikTok moderation, account restrictions, or platform safeguards.
- Keep publishing actions consistent with the creator's current authorization. A review pass is not permission to publish if the creator has not authorized that publishing flow.

## 7. Manual export approval

Every generated TikTok export includes `REVIEW_REQUIRED.txt`. It starts in a NOT REVIEWED / DO NOT POST state. The person preparing the post must watch the complete exported MP4 and tick every item before uploading. The checklist is not an automated visual or legal determination. A full-frame fit protects against the renderer cropping out a facecam, but cannot prove that a facecam exists in the source or that the streamer is recognizable. Uncertain clips stay unpublished.

## 7a. Held clips are listed, not silently dropped

Every export writes a "Zurückgehalten (NICHT exportiert)" section into `CAPTIONS.md` that names each held streamer or clip and the reason: missing HTTPS permission link, risky title word (`gta_filter.title_blocklist`, e.g. leak/doxx/adresse), failed render or missing subtitles, or a caption that fails the checks (misleading claims such as leak/exclusive/official, engagement bait such as "follow for part 2" or "like if", URLs, source lines, stock questions). The vertical render fits the whole source frame over a blurred background (no black bars).

## 8. Recordkeeping

For each clip, retain its source reference, review result, caption, hashtags, and upload outcome. Do not store account passwords, access tokens, or other secrets in this document or in source control.
