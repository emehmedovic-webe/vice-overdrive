const TT = 'https://open.tiktokapis.com/v2';
const CAP = 24 * 1024 * 1024;
const SESSION = '__Host-vo_session';
const STATE = '__Host-vo_state';
const PURPOSE = {session: 'vo-session-v1', status: 'vo-status-v1'};
const encode = new TextEncoder();
const decoder = new TextDecoder();
const b64 = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const unb64 = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const cookie = (name, value, seconds) =>
  `${name}=${value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${seconds}`;
const readCookie = (request, name) => (request.headers.get('Cookie') || '').split(';')
  .map(s => s.trim()).find(s => s.startsWith(name + '='))?.slice(name.length + 1);
const secure = {
  'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Content-Security-Policy': "default-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
};
const json = (data, status = 200) => Response.json(data, {
  status, headers: {...secure, 'Cache-Control': 'no-store'}
});
const jump = (url, cookies = []) => {
  const headers = new Headers({...secure, 'Cache-Control': 'no-store', Location: url});
  for (const value of cookies) headers.append('Set-Cookie', value);
  return new Response(null, {status: 303, headers});
};
class Failure extends Error {
  constructor(code, status = 400) { super(code); this.status = status; }
}
function https(value) {
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && !url.username && !url.password) return url;
  } catch {}
  return null;
}
async function config(env, url) {
  const site = https(env.APP_ORIGIN);
  const privacy = https(env.PRIVACY_POLICY_URL);
  const terms = https(env.TERMS_URL);
  let key;
  try {
    const bytes = unb64(env.SESSION_KEY);
    if (bytes.length === 32) key = await crypto.subtle.importKey('raw', bytes, 'AES-GCM', false, ['encrypt', 'decrypt']);
  } catch {}
  if (site?.origin !== url.origin || site.href !== site.origin + '/' ||
      !env.TIKTOK_CLIENT_KEY || !env.TIKTOK_CLIENT_SECRET || !privacy || !terms || !key ||
      [privacy, terms].some(link => link.origin === site.origin && ['/', '/privacy', '/terms'].includes(link.pathname))) {
    throw new Failure('studio_not_configured', 503);
  }
  return {site, privacy, terms, key, client: env.TIKTOK_CLIENT_KEY, secret: env.TIKTOK_CLIENT_SECRET};
}
async function seal(key, purpose, value) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const bytes = await crypto.subtle.encrypt({name:'AES-GCM', iv, additionalData:encode.encode(purpose)},
    key, encode.encode(JSON.stringify(value)));
  return b64(Uint8Array.of(...iv, ...new Uint8Array(bytes)));
}
async function unseal(key, purpose, value) {
  try {
    if (!value || value.length > 3900) return null;
    const bytes = unb64(value);
    const contents = await crypto.subtle.decrypt({name:'AES-GCM', iv:bytes.subarray(0, 12), additionalData:encode.encode(purpose)},
      key, bytes.subarray(12));
    const result = JSON.parse(decoder.decode(contents));
    return result.until > Date.now() ? result : null;
  } catch { return null; }
}
function tokenHeader(token) { return {Authorization: `Bearer ${token}`}; }
function code(value, fallback) { return typeof value === 'string' && /^[a-zA-Z0-9_]{1,80}$/.test(value) ? value : fallback; }
function bool(value) { return typeof value === 'boolean'; }
function basicHeaderCheck(request, max) {
  const length = request.headers.get('Content-Length');
  if (!length || !/^\d+$/.test(length)) throw new Failure('missing_content_length', 411);
  if (Number(length) > max) throw new Failure('request_too_large', 413);
}
function safeUpload(value) {
  const url = https(value);
  return url && !url.port && !url.hash &&
    /^(?:open-upload|upload(?:\.[a-z0-9-]+)?)\.tiktokapis\.com$/.test(url.hostname) ? url : null;
}
async function checkMp4(file) {
  if (!(file instanceof Blob) || file.type !== 'video/mp4' || file.size < 16 || file.size > CAP) {
    throw new Failure('select_mp4_under_24_mib');
  }
  const start = await file.slice(0, 12).arrayBuffer();
  if (decoder.decode(start.slice(4, 8)) !== 'ftyp' || new DataView(start).getUint32(0) < 16) {
    throw new Failure('invalid_mp4_header');
  }
}
async function requestJSON(request) {
  basicHeaderCheck(request, 5000);
  try { return await request.json(); } catch { throw new Failure('invalid_json'); }
}
export function makeStudio(fetcher = fetch) {
  async function api(path, token, body) {
    let response, result;
    try {
      response = await fetcher(TT + path, {...(body === undefined ? {} : {method:'POST', body:JSON.stringify(body)}),
        headers: {...tokenHeader(token), 'Content-Type':'application/json'}, redirect:'error'});
      result = await response.json();
    } catch { throw new Failure('tiktok_unavailable', 502); }
    if (!response.ok || result?.error?.code !== 'ok' || !result?.data) {
      throw new Failure(code(result?.error?.code === 'ok' ? null : result?.error?.code, 'tiktok_request_failed'),
        response.status === 401 ? 401 : response.status === 429 ? 429 : 422);
    }
    return result.data;
  }
  async function creator(session) {
    const info = await api('/post/publish/creator_info/query/', session.token, {});
    if (!info.creator_username || !Array.isArray(info.privacy_level_options) ||
        !['comment_disabled','duet_disabled','stitch_disabled'].every(key => bool(info[key])) ||
        !(info.max_video_post_duration_sec > 0)) throw new Failure('creator_info_incomplete', 502);
    return {username:info.creator_username, nickname:info.creator_nickname || info.creator_username,
      visibility:info.privacy_level_options.filter(v => ['PUBLIC_TO_EVERYONE','MUTUAL_FOLLOW_FRIENDS','FOLLOWER_OF_CREATOR','SELF_ONLY'].includes(v)),
      comments:!info.comment_disabled, duet:!info.duet_disabled, stitch:!info.stitch_disabled,
      maxDuration:info.max_video_post_duration_sec};
  }
  async function handle(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (!path.startsWith('/api/') && !path.startsWith('/auth/') && path !== '/privacy' && path !== '/terms') {
      const asset = await env.ASSETS.fetch(request);
      const headers = new Headers(asset.headers);
      for (const [key, value] of Object.entries(secure)) headers.set(key, value);
      return new Response(asset.body, {status:asset.status, headers});
    }
    const c = await config(env, url);
    if (request.method === 'GET' && path === '/privacy') return jump(c.privacy.href);
    if (request.method === 'GET' && path === '/terms') return jump(c.terms.href);
    if (request.method === 'GET' && path === '/auth/login') {
      const state = random();
      const target = new URL('https://www.tiktok.com/v2/auth/authorize/');
      target.search = new URLSearchParams({client_key:c.client, response_type:'code',
        scope:'user.info.basic,video.publish', redirect_uri:c.site.origin + '/auth/callback', state});
      return jump(target.href, [cookie(STATE, state, 600)]);
    }
    if (request.method === 'GET' && path === '/auth/callback') {
      const state = readCookie(request, STATE);
      const clear = cookie(STATE, '', 0);
      const clearSession = cookie(SESSION, '', 0);
      if (!state || !/^[A-Za-z0-9_-]{43}$/.test(state) || state !== url.searchParams.get('state') ||
          !url.searchParams.get('code') || url.searchParams.has('error')) return jump('/?auth=failed', [clear]);
      try {
        const response = await fetcher(TT + '/oauth/token/', {method:'POST', redirect:'error',
          headers:{'Content-Type':'application/x-www-form-urlencoded'},
          body:new URLSearchParams({client_key:c.client,client_secret:c.secret,code:url.searchParams.get('code'),
            grant_type:'authorization_code',redirect_uri:c.site.origin + '/auth/callback'})});
        const data = await response.json();
        const scopes = String(data?.scope || '').split(/[\s,]+/);
        const ttl = Math.min(43200, Math.floor(Number(data?.expires_in)));
        if (!response.ok || !scopes.includes('video.publish') || !scopes.includes('user.info.basic') ||
            typeof data.access_token !== 'string' || !data.access_token || data.access_token.length > 1800 || !(ttl > 0)) {
          return jump('/?auth=scope', [clear, clearSession]);
        }
        const profile = await api('/user/info/?fields=open_id,display_name', data.access_token);
        if (!profile.user?.open_id || profile.user.open_id !== data.open_id) return jump('/?auth=failed', [clear, clearSession]);
        const value = await seal(c.key, PURPOSE.session, {token:data.access_token, user:profile.user.open_id,
          name:String(profile.user.display_name || '').slice(0, 160), id:random(), until:Date.now() + ttl * 1000});
        return jump('/', [clear, cookie(SESSION, value, ttl)]);
      } catch { return jump('/?auth=failed', [clear, clearSession]); }
    }
    if (request.method !== 'GET' &&
        (request.method !== 'POST' || request.headers.get('Origin') !== c.site.origin)) {
      throw new Failure('invalid_request_origin', 403);
    }
    if (request.method === 'POST' && path === '/api/logout') return jump('/', [cookie(SESSION,'',0)]);
    const session = await unseal(c.key, PURPOSE.session, readCookie(request, SESSION));
    if (!session) throw new Failure('connect_tiktok', 401);
    if (path === '/api/creator' && request.method === 'GET') {
      return json({...await creator(session), profileName:session.name});
    }
    if (path === '/api/post' && request.method === 'POST') {
      basicHeaderCheck(request, CAP + 12 * 1024);
      if (!request.headers.get('Content-Type')?.startsWith('multipart/form-data;')) throw new Failure('invalid_form');
      let form, meta;
      try { form = await request.formData(); meta = JSON.parse(form.get('meta')); } catch { throw new Failure('invalid_form'); }
      if (!meta || meta.consent !== true || meta.ownsContent !== true) throw new Failure('posting_requires_consent');
      if (typeof meta.caption !== 'string' || meta.caption.length > 2200 || !meta.caption.trim() ||
          typeof meta.duration !== 'number' || !(meta.duration > 0) ||
          !['comments','duet','stitch','commercial','ownBrand','thirdParty'].every(k => bool(meta[k])) ||
          !meta.commercial && (meta.ownBrand || meta.thirdParty) || meta.commercial && !meta.ownBrand && !meta.thirdParty) {
        throw new Failure('invalid_post_settings');
      }
      const file = form.get('video');
      await checkMp4(file);
      const fresh = await creator(session);
      if (fresh.username !== meta.creator) throw new Failure('creator_changed_review_again', 409);
      if (!fresh.visibility.includes(meta.visibility) || meta.duration > fresh.maxDuration ||
          meta.thirdParty && meta.visibility === 'SELF_ONLY' ||
          ['comments','duet','stitch'].some(k => meta[k] && !fresh[k])) {
        throw new Failure('creator_settings_changed_review_again', 409);
      }
      const data = await api('/post/publish/video/init/', session.token, {
        post_info:{title:meta.caption.trim(),privacy_level:meta.visibility,disable_comment:!meta.comments,
          disable_duet:!meta.duet,disable_stitch:!meta.stitch,brand_content_toggle:meta.thirdParty,
          brand_organic_toggle:meta.ownBrand},
        source_info:{source:'FILE_UPLOAD',video_size:file.size,chunk_size:file.size,total_chunk_count:1}
      });
      if (typeof data.publish_id !== 'string' || !data.publish_id) throw new Failure('missing_publish_id', 502);
      const target = safeUpload(data.upload_url);
      if (!target) throw new Failure('invalid_tiktok_upload_host', 502);
      const ticket = await seal(c.key, PURPOSE.status, {sid:session.id, publishId:data.publish_id, until:session.until});
      try {
        const transfer = await fetcher(target.href, {method:'PUT',body:file,redirect:'error',headers:{
          'Content-Type':'video/mp4','Content-Length':String(file.size),'Content-Range':`bytes 0-${file.size-1}/${file.size}`
        }});
        if (!transfer.ok) return json({ticket, transfer:'unknown'});
      } catch { return json({ticket, transfer:'unknown'}); }
      return json({ticket, transfer:'sent'});
    }
    if (path === '/api/status' && request.method === 'POST') {
      const body = await requestJSON(request);
      const ticket = await unseal(c.key, PURPOSE.status, body?.ticket);
      if (!ticket || ticket.sid !== session.id) throw new Failure('invalid_status_ticket', 403);
      const data = await api('/post/publish/status/fetch/', session.token, {publish_id:ticket.publishId});
      return json({status:code(data.status,'UNKNOWN'), failure:code(data.fail_reason,'')});
    }
    return json({error:'not_found'}, 404);
  }
  return { async fetch(request, env) {
    try { return await handle(request, env); }
    catch (err) { return err instanceof Failure ? json({error:err.message},err.status) : json({error:'studio_error'},500); }
  }};
}
export default makeStudio();
