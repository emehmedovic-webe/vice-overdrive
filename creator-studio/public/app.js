'use strict';
const byId = id => document.getElementById(id);
const ui = Object.fromEntries(Array.from(document.querySelectorAll('[id]'), el => [el.id, el]));
const labels = {PUBLIC_TO_EVERYONE:'Everyone',MUTUAL_FOLLOW_FRIENDS:'Friends',FOLLOWER_OF_CREATOR:'Followers',SELF_ONLY:'Only me'};
const errorMessage = {
  studio_not_configured:'TikTok sign-in is not configured for this website yet.',
  connect_tiktok:'Connect a TikTok account to select visibility and post.',
  posting_requires_consent:'Confirm you own the video and expressly agree to post it.',
  creator_settings_changed_review_again:'TikTok’s settings changed. Review the available options and select visibility again.',
  creator_changed_review_again:'The active TikTok account changed. Review the account and settings before posting.',
  spam_risk_too_many_posts:'TikTok has reached its posting limit for this account.',
  spam_risk_user_banned_from_posting:'This account cannot post through TikTok right now.',
  unaudited_client_can_only_post_to_private_accounts:'The current TikTok app can only test private posts with private accounts.',
  select_mp4_under_24_mib:'Choose an MP4 file under 24 MiB.',
  invalid_mp4_header:'The selected file is not a supported MP4.',
  tiktok_unavailable:'TikTok could not be reached.',
  invalid_access_token:'Your TikTok session expired. Connect again.'
};
const message = e => errorMessage[e.message] || 'Request failed (' + e.message + ').';
const status = content => { ui['post-status'].textContent = content; };
let creator, selectedVideo, objectUrl, duration = 0, busy = false, ticket, unresolved = false;
const storeKey = 'vo-studio-pending';
const stash = value => { try { value ? sessionStorage.setItem(storeKey,value) : sessionStorage.removeItem(storeKey); } catch {} };
try { ticket = sessionStorage.getItem(storeKey); } catch {}
const fields = ['comments','duet','stitch'];
async function request(path, options = {}) {
  const r = await fetch(path, {...options, cache:'no-store', credentials:'same-origin'});
  const result = await r.json();
  if (!r.ok) throw new Error(result.error || 'unknown_error');
  return result;
}
function evaluate() {
  const privateOption = Array.from(ui.visibility.options).find(option => option.value === 'SELF_ONLY');
  const privateSelected = ui.visibility.value === 'SELF_ONLY';
  ui['brand-options'].hidden = !ui.commercial.checked;
  if (!ui.commercial.checked) ui.ownBrand.checked = ui.thirdParty.checked = false;
  ui.thirdParty.disabled = privateSelected;
  if (privateSelected) ui.thirdParty.checked = false;
  if (privateOption) privateOption.disabled = ui.commercial.checked && ui.thirdParty.checked;
  ui['brand-consent'].hidden = !ui.thirdParty.checked;
  ui['disclosure-label'].textContent = ui.thirdParty.checked ? 'TikTok label: Paid partnership.' :
    ui.ownBrand.checked ? 'TikTok label: Promotional content.' :
    privateSelected ? 'Third-party branded content cannot be private.' : 'Choose at least one disclosure.';
  ui.count.textContent = ui.caption.value.length + ' / 2200';
  const canPost = Boolean(creator && selectedVideo && duration > 0 && duration <= creator.maxDuration &&
    ui.caption.value.trim() && ui.visibility.value && ui.owned.checked &&
    (!ui.commercial.checked || ui.ownBrand.checked || ui.thirdParty.checked));
  ui.consent.disabled = !canPost || busy || Boolean(ticket) || unresolved;
  if (!canPost) ui.consent.checked = false;
  ui.publish.disabled = ui.consent.disabled || !ui.consent.checked;
  ui['check-status'].hidden = !ticket;
  ui['check-status'].disabled = busy;
}
async function loadCreator() {
  ui.visibility.replaceChildren(new Option('Choose visibility',''));
  ui.visibility.disabled = ui.interactions.disabled = ui.disclosures.disabled = true;
  creator = undefined;
  ui.consent.checked = false;
  try {
    creator = await request('/api/creator');
    ui.account.textContent = (creator.nickname || creator.profileName) + ' (@' + creator.username + ') · up to ' + creator.maxDuration + ' seconds.';
    for (const name of creator.visibility) if (labels[name]) ui.visibility.add(new Option(labels[name],name));
    ui.visibility.disabled = ui.interactions.disabled = ui.disclosures.disabled = false;
    ui.connect.hidden = true;
    ui.logout.hidden = false;
    for (const name of fields) {
      byId(name).checked = false;
      byId(name).disabled = !creator[name];
    }
    if (!creator.visibility.length) ui.account.textContent += ' TikTok returned no posting options for this account.';
    if (ticket) status('A previous transfer is pending. Check its status before retrying.');
  } catch (e) {
    const auth = new URL(location.href).searchParams.get('auth');
    ui.account.textContent = auth === 'scope' ? 'Please grant both TikTok permissions to connect.' :
      auth === 'failed' ? 'TikTok sign-in did not finish. Please connect again.' : message(e);
    ui.connect.hidden = e.message === 'studio_not_configured';
    ui.logout.hidden = false;
  }
  evaluate();
}
ui.clip.addEventListener('change', () => {
  ui.consent.checked = ui.owned.checked = false;
  duration = 0;
  selectedVideo = undefined;
  ui.preview.hidden = false;
  ui.preview.removeAttribute('src');
  ui.preview.load();
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = '';
  ui.preview.hidden = true;
  ui['empty-preview'].hidden = false;
  const file = ui.clip.files[0];
  if (!file || (file.type && file.type !== 'video/mp4') || !/\.mp4$/i.test(file.name) || file.size > 24 * 1024 * 1024) {
    ui['clip-info'].textContent = file ? errorMessage.select_mp4_under_24_mib : 'Choose a clip to preview.';
    evaluate();
    return;
  }
  ui['clip-info'].textContent = 'Checking video…';
  selectedVideo = file;
  objectUrl = URL.createObjectURL(file);
  ui.preview.src = objectUrl;
  ui.preview.hidden = false;
  ui['empty-preview'].hidden = true;
  evaluate();
});
ui.preview.addEventListener('loadedmetadata', () => {
  if (!selectedVideo || !Number.isFinite(ui.preview.duration)) return;
  duration = ui.preview.duration;
  ui['clip-info'].textContent = duration.toFixed(1) + ' s · ' +
    (creator && duration > creator.maxDuration ? 'Too long for the connected TikTok account.' : 'Ready to preview.');
  evaluate();
});
ui.preview.addEventListener('error', () => {
  if (!objectUrl) return;
  duration = 0;
  ui['clip-info'].textContent = 'This video could not be previewed. Select another MP4.';
  evaluate();
});
ui.editor.addEventListener('input', e => {
  if (e.target !== ui.consent) ui.consent.checked = false;
  evaluate();
});
async function poll(tries = 1) {
  for (let i = 0; i < tries; i++) {
    if (i) await new Promise(resolve => setTimeout(resolve, 8000));
    try {
      const result = await request('/api/status', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket})});
      if (result.status === 'PUBLISH_COMPLETE' || result.status === 'FAILED') {
        status(result.status === 'PUBLISH_COMPLETE' ? 'TikTok confirmed the post was published.' :
          'TikTok could not publish this clip' + (result.failure ? ' (' + result.failure + ').' : '.'));
        ticket = null;
        stash(null);
        ui.consent.checked = false;
        if (result.status === 'PUBLISH_COMPLETE') {
          ui.clip.value = '';
          ui.clip.dispatchEvent(new Event('change'));
        }
        return;
      }
      status('TikTok status: ' + result.status.toLowerCase().replaceAll('_',' ') + '. Check again if this takes longer.');
    } catch (e) { status('Could not check TikTok status. ' + message(e)); return; }
  }
}
ui['check-status'].addEventListener('click', async () => {
  if (!ticket || busy) return;
  busy = true;
  evaluate();
  await poll();
  busy = false;
  evaluate();
});
ui.editor.addEventListener('submit', async e => {
  e.preventDefault();
  if (ui.publish.disabled || busy) return;
  const payload = new FormData();
  payload.set('video', selectedVideo.type === 'video/mp4' ? selectedVideo :
    new File([selectedVideo],selectedVideo.name,{type:'video/mp4'}));
  payload.set('meta', JSON.stringify({
    creator:creator.username, caption:ui.caption.value, duration, visibility:ui.visibility.value,
    comments:ui.comments.checked, duet:ui.duet.checked, stitch:ui.stitch.checked, commercial:ui.commercial.checked,
    ownBrand:ui.ownBrand.checked, thirdParty:ui.thirdParty.checked, consent:ui.consent.checked, ownsContent:ui.owned.checked
  }));
  busy = true;
  ui.consent.checked = false;
  evaluate();
  status('Sending your approved clip to TikTok…');
  try {
    const result = await request('/api/post',{method:'POST',body:payload});
    ticket = result.ticket;
    stash(ticket);
    status(result.transfer === 'sent' ? 'Clip sent. Waiting for TikTok to confirm…' :
      'TikTok has not confirmed the transfer. Checking its status…');
    await poll(5);
  } catch (e) {
    status(message(e));
    if (['creator_changed_review_again','creator_settings_changed_review_again'].includes(e.message)) await loadCreator();
    else if (e instanceof TypeError || e instanceof SyntaxError) {
      unresolved = true;
      status('The request result is unknown. Check your TikTok profile before trying again.');
    }
  } finally { busy = false; evaluate(); }
});
ui.logout.addEventListener('submit',()=>stash(null));
loadCreator();
