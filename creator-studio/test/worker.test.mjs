import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {makeStudio} from '../src/worker.mjs';

const origin = 'https://studio.example.org';
const env = {
  APP_ORIGIN:origin, TIKTOK_CLIENT_KEY:'mock-key', TIKTOK_CLIENT_SECRET:'mock-secret',
  SESSION_KEY:Buffer.alloc(32,123).toString('base64'),
  PRIVACY_POLICY_URL:origin+'/legal/privacy', TERMS_URL:origin+'/legal/terms',
  ASSETS:{fetch:async request=>new Response(new URL(request.url).pathname)}
};
const names = {state:'__Host-vo_state',session:'__Host-vo_session'};
const req = (path, options) => new Request(origin+path,options);
const tick = data => Response.json({data,error:{code:'ok'}});
const fakeMp4 = new Uint8Array(32);
fakeMp4[3]=24;
fakeMp4.set(Buffer.from('ftypisom'),4);
const base = {
  creator:'gamer17',caption:'One last jump held the lead. #Gaming',duration:7, visibility:'SELF_ONLY',
  comments:false,duet:false,stitch:false,commercial:false,ownBrand:false,thirdParty:false,consent:true,ownsContent:true
};

function fixture({upload='https://upload.us.tiktokapis.com/upload/?upload_token=opaque',transfer=201,publicProfile=false,missingScope=false}={}) {
  const calls = [];
  let account = 'gamer17';
  const studio = makeStudio(async (url, args) => {
    const address = new URL(url);
    calls.push({url:address,args});
    if (address.hostname === 'upload.us.tiktokapis.com') {
      if (transfer === 'throw') throw new Error('transport interrupted');
      assert.equal(args.method,'PUT');
      assert.equal(args.redirect,'error');
      assert.equal(args.headers['Content-Length'],'32');
      assert.equal(args.headers['Content-Range'],'bytes 0-31/32');
      assert.deepEqual(new Uint8Array(await args.body.arrayBuffer()),fakeMp4);
      return new Response(null,{status:transfer});
    }
    if (address.pathname.endsWith('/oauth/token/')) {
      assert.equal(args.body.get('code'),'testing-code');
      assert.equal(args.body.get('redirect_uri'),origin+'/auth/callback');
      assert.equal(args.body.get('client_secret'),'mock-secret');
      return Response.json({open_id:'mock-user',access_token:'mock-access',expires_in:3600,
        scope:missingScope?'user.info.basic':'user.info.basic,video.publish'});
    }
    assert.equal(args.headers.Authorization,'Bearer mock-access');
    if (address.pathname.endsWith('/user/info/')) {
      assert.equal(address.searchParams.get('fields'),'open_id,display_name');
      return tick({user:{open_id:'mock-user',display_name:'Gamer'}});
    }
    if (address.pathname.endsWith('/creator_info/query/')) return tick({
      creator_nickname:'The Gamer',creator_username:account,duet_disabled:true,comment_disabled:false,stitch_disabled:false,
      privacy_level_options:publicProfile?['PUBLIC_TO_EVERYONE','SELF_ONLY']:['SELF_ONLY'],max_video_post_duration_sec:60
    });
    if (address.pathname.endsWith('/video/init/')) return tick({publish_id:'mock-post',upload_url:upload});
    if (address.pathname.endsWith('/status/fetch/')) return tick({status:'PUBLISH_COMPLETE'});
    throw new Error('unexpected test request');
  });
  const call = (path,opts) => studio.fetch(req(path,opts),env);
  async function login(overrides = {}) {
    const start = await call('/auth/login');
    assert.equal(start.status,303);
    const target = new URL(start.headers.get('Location'));
    assert.equal(target.origin,'https://www.tiktok.com');
    const cookie = start.headers.get('Set-Cookie').split(';')[0];
    assert.ok(cookie.startsWith(names.state+'='));
    assert.match(start.headers.get('Set-Cookie'),/Secure; HttpOnly; SameSite=Lax/);
    const state = overrides.state || target.searchParams.get('state');
    return call('/auth/callback?code=testing-code&state='+state,{headers:{Cookie:cookie}});
  }
  const session = response => response.headers.getSetCookie().find(c=>c.startsWith(names.session+'='))?.split(';')[0];
  async function post(session, extra={}, overrideOrigin=origin) {
    const form = new FormData();
    form.append('video',new Blob([fakeMp4],{type:'video/mp4'}),'own-clip.mp4');
    form.append('meta',JSON.stringify({...base,...extra}));
    const request = req('/api/post',{method:'POST',body:form});
    const bytes = await request.arrayBuffer();
    return call('/api/post',{method:'POST',body:bytes,headers:{
      Cookie:session,Origin:overrideOrigin,'Content-Type':request.headers.get('Content-Type'),'Content-Length':String(bytes.byteLength)
    }});
  }
  async function status(session,ticket) {
    const body = JSON.stringify({ticket});
    return call('/api/status',{method:'POST',body,headers:{
      Cookie:session,Origin:origin,'Content-Type':'application/json','Content-Length':String(Buffer.byteLength(body))
    }});
  }
  return {call,calls,login,session,post,status,changeAccount:value=>{account=value;}};
}
test('public pages and privacy links, but no posting without sign-in',async()=>{
  const f=fixture();
  const landing=await f.call('/');
  assert.match(landing.headers.get('Content-Security-Policy'),/media-src 'self' blob:/);
  assert.equal((await f.call('/privacy')).headers.get('Location'),env.PRIVACY_POLICY_URL);
  assert.equal((await f.call('/terms')).headers.get('Location'),env.TERMS_URL);
  assert.equal((await f.call('/api/creator')).status,401);
  const disabled = await makeStudio().fetch(req('/api/creator'),{...env,TIKTOK_CLIENT_SECRET:''});
  assert.equal(disabled.status,503);
  assert.equal(f.calls.length,0);
});
test('invalid OAuth state does not call provider and missing scopes do not create a session',async()=>{
  const f=fixture();
  const bad=await f.login({state:'wrong'});
  assert.equal(bad.headers.get('Location'),'/?auth=failed');
  assert.equal(f.calls.length,0);
  const limited=fixture({missingScope:true});
  const failure=await limited.login();
  assert.equal(failure.headers.get('Location'),'/?auth=scope');
  assert.equal(limited.session(failure),names.session+'=');
});
test('OAuth makes a sealed multi-user session and shows current creator options',async()=>{
  const f=fixture();
  const session=f.session(await f.login());
  assert.ok(session);
  assert.doesNotMatch(session,/mock-access|mock-user/);
  const r=await f.call('/api/creator',{headers:{Cookie:session}});
  assert.deepEqual(await r.json(),{username:'gamer17',nickname:'The Gamer',visibility:['SELF_ONLY'],
    comments:true,duet:false,stitch:true,maxDuration:60,profileName:'Gamer'});
});
test('cross-origin or unchecked approval never reaches TikTok',async()=>{
  const f=fixture();
  const session=f.session(await f.login());
  f.calls.length=0;
  assert.equal((await f.post(session,{},'https://attacker.example')).status,403);
  assert.equal((await f.post(session,{consent:false})).status,400);
  assert.equal((await f.post(session,{ownsContent:false})).status,400);
  assert.equal(f.calls.length,0);
});
test('actual account change, empty visibility, private branded, and invalid settings block posting',async()=>{
  const f=fixture();
  const session=f.session(await f.login());
  f.calls.length=0;
  for (const extra of [{visibility:''},{duet:true},{duration:61},{commercial:true,thirdParty:true},{visibility:'PUBLIC_TO_EVERYONE'}]) {
    const r=await f.post(session,extra);
    assert.equal(r.status,409);
  }
  f.changeAccount('another_account');
  assert.equal((await f.post(session)).status,409);
  assert.ok(f.calls.every(x=>x.url.pathname.endsWith('/creator_info/query/')));
});
test('publish approves a single transfer, sends the exact caption and separately confirms published status',async()=>{
  const f=fixture({publicProfile:true});
  const session=f.session(await f.login());
  const {ticket,transfer}=await (await f.post(session,{
    visibility:'PUBLIC_TO_EVERYONE',comments:true,commercial:true,thirdParty:true
  })).json();
  assert.equal(transfer,'sent');
  const init = f.calls.find(x=>x.url.pathname.endsWith('/video/init/'));
  assert.deepEqual(JSON.parse(init.args.body),{
    post_info:{title:base.caption,privacy_level:'PUBLIC_TO_EVERYONE',disable_comment:false,disable_duet:true,
      disable_stitch:true,brand_content_toggle:true,brand_organic_toggle:false},
    source_info:{source:'FILE_UPLOAD',video_size:32,chunk_size:32,total_chunk_count:1}
  });
  assert.doesNotMatch(ticket,/mock-post/);
  assert.equal((await (await f.status(session,ticket)).json()).status,'PUBLISH_COMPLETE');
  assert.equal(JSON.parse(f.calls.find(x=>x.url.pathname.endsWith('/status/fetch/')).args.body).publish_id,'mock-post');
  const other=f.session(await f.login());
  assert.equal((await f.status(other,ticket)).status,403);
  assert.equal((await f.status(session,'bad'+ticket)).status,403);
});
test('rejects unsafe media host, and uncertain transfer never retries or claims successful publication',async()=>{
  const unsafe=fixture({upload:'https://upload.us.tiktokapis.com.attacker.example/u'});
  const s=unsafe.session(await unsafe.login());
  assert.equal((await unsafe.post(s)).status,502);
  assert.ok(unsafe.calls.every(x=>x.url.hostname==='open.tiktokapis.com'));
  const f=fixture({transfer:'throw'});
  const session=f.session(await f.login());
  const result=await (await f.post(session)).json();
  assert.equal(result.transfer,'unknown');
  assert.ok(result.ticket);
  assert.equal(f.calls.filter(x=>x.args.method==='PUT').length,1);
});
test('just previewing is local and the form has no pre-selected visibility or interactions',async()=>{
  const html=await readFile(new URL('../public/index.html',import.meta.url),'utf8');
  const js=await readFile(new URL('../public/app.js',import.meta.url),'utf8');
  assert.match(html,/<select id="visibility" required disabled><option value="">/);
  for (const field of ['comments','duet','stitch','commercial','consent']) {
    assert.doesNotMatch(html,new RegExp('id="'+field+'"[^>]+ checked'));
  }
  assert.match(js,/URL.createObjectURL\(file\)/);
  assert.match(js,/result.status === 'PUBLISH_COMPLETE'/);
});
