# VICE OVERDRIVE Creator Studio

Independent web app for creators to preview their own gaming clips, write an editable caption and post to their own connected TikTok account. It neither imports videos from other platforms nor talks to the existing VICE OVERDRIVE AutoPilot, YouTube workflow, or TikTok Inbox workflow. It never posts without a creator reviewing and approving the individual post.

## Before the TikTok submission

1. Put this Worker and its website on your own public HTTPS host. A Cloudflare Worker can run it without any installation or background process on the Mac. Confirm the host, its account, and the plan before deployment. Use a host that you control and can verify at TikTok.
2. Publish real, visible privacy and terms pages for this product, with the actual operator and their contact details. Check that the privacy notice describes the real flow: login identity and session, temporary relay of an approved video and caption to TikTok, browser session data and hosting logs, and how to disconnect and revoke access. The app does not save video files or captions. Do not carry over disclosures from the old personal bot without checking them.
3. Configure the origin (just the scheme and host), active privacy and terms URLs, and a separate set of TikTok app credentials on the Worker. Set the final website and the exact HTTPS callback ending in `/auth/callback` in the TikTok Web app settings. Verify the relevant URLs in the Developer Portal. Use the sandbox credentials for the demo and a designated private test account, not a public production account. Do not change the old bot credentials.
4. In TikTok Sandbox, enable **Login Kit** and **Content Posting API → Direct Post**. Request `user.info.basic` (check the authenticated identity and show the account) and `video.publish` (publish the approved local clip). Do not request `video.upload` for this integration. Register the test account in Sandbox Target users and apply the sandbox configuration. For the test, use an original H.264 MP4 under 24 MiB with permitted audio and select **Only me** yourself. Sandbox does not offer public video posting.
5. Record the real website on the same domain given to TikTok. Show sign-in and TikTok permissions, the connected user, local video preview, caption edit, explicit visibility choice with no default, interaction controls, commercial disclosure settings, consent, **Post to TikTok**, processing and the confirmed private result on TikTok. One end-to-end demo is sufficient if it covers every requested scope. Keep each demo video within 50 MB and keep credentials or tokens off-screen. The mock test harness is not a substitute for this video.
6. Fill in **App review** and upload the demo. Use the short form reason below only once the integration is deployed and the demo actually works. App Review and the Direct Post audit are separate. Public posting stays off-limits until TikTok approves the relevant permissions and removes the audit restrictions. If the actual product use is still only a private uploader for the operator's accounts, do not submit it as a public creator service.

**Short “Submit for review” reason (under 120 characters)**

> Review VICE OVERDRIVE Studio's TikTok sign-in and creator-approved posting of original gaming videos.

**Suggested detailed review text (use only after validating it against the demo)**

> VICE OVERDRIVE Creator Studio helps creators preview their original gaming clips and prepare captions before sharing them to TikTok. Login Kit and user.info.basic let us confirm the signed-in identity and show which account is connected. Content Posting API with video.publish lets that creator send a selected video only after reviewing the clip and caption, selecting visibility and required disclosures, and explicitly approving the post. The website displays TikTok's processing result. Our sandbox demo uses a private test account with Only me visibility.

## Deployment settings

Deploy the `creator-studio/` directory using `wrangler.toml`. Use host dashboard variables and secrets or an authorized CI runner. Set:

| Setting | Value |
|---|---|
| `APP_ORIGIN` | Exact public HTTPS origin of the Studio, without a path |
| `PRIVACY_POLICY_URL` | Real public privacy policy for the Studio |
| `TERMS_URL` | Real public terms for the Studio |
| `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` | Studio’s TikTok credentials for the active environment |
| `SESSION_KEY` | A randomly generated 32-byte key encoded as base64, stored as a secret |

No production credentials are included. Use a separate environment and credentials for production, and keep the sandbox integration at the submitted demo URL until the review is complete. Short-lived sessions are encrypted and use a Secure HttpOnly cookie. There is no background refresh or video storage. Disconnect clears this browser's session. Creators can revoke authorization in TikTok settings. The app relays only a creator-approved upload over HTTPS, then uses a user-session-bound ticket to check status.

## Offline verification

Run `node --test creator-studio/test/*.test.mjs` from the repository root using Node 22 or newer. It uses fake OAuth identities and demonstrates that preview does not upload, consent and allowed settings are enforced, and publication is only marked done after TikTok reports completion. It makes no real uploads.

## TikTok references

- [App Review Guidelines](https://developers.tiktok.com/doc/app-review-guidelines)
- [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines)
- [Sandbox](https://developers.tiktok.com/doc/add-a-sandbox)
- [Direct Post integration](https://developers.tiktok.com/doc/content-posting-api-get-started)
