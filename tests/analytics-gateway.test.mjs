import assert from 'node:assert/strict';
import { test, beforeEach, afterEach } from 'node:test';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import ts from 'typescript';
const require = createRequire(import.meta.url), cache = new Map();
function load(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = {exports:{}};
  cache.set(path,module);
  const code = ts.transpileModule(readFileSync(path,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const req = name => name.startsWith('.') ? load(resolve(dirname(path), name)+'.ts') : require(name);
  new Function('require','module','exports',code)(req,module,module.exports);
  return module.exports;
}
const {POST} = load(resolve('apps/web/app/api/landing/analytics/route.ts'));
const {GET} = load(resolve('apps/web/app/api/landing/analytics/config/route.ts'));
const {analyticsContext, classifyAnalyticsClick} = load(resolve('apps/web/lib/landing-analytics.ts'));
const originalFetch = globalThis.fetch;
const saved = { ...process.env };
let calls;
beforeEach(() => {
  calls = [];
  process.env.CRM_ORIGIN = 'https://jardinesdelencanto.site';
  process.env.UMAMI_ENABLED = '1';
  process.env.UMAMI_BASE_URL = 'http://umami:3000';
  process.env.UMAMI_WEBSITE_ID = '10000000-0000-4000-8000-000000000001';
  process.env.UMAMI_TRUST_PROXY = '0';
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return Response.json({ sessionId: 'private' }); };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  for (const name of ['CRM_ORIGIN','UMAMI_ENABLED','UMAMI_BASE_URL','UMAMI_WEBSITE_ID','UMAMI_TRUST_PROXY']) {
    if (saved[name] === undefined) delete process.env[name]; else process.env[name] = saved[name];
  }
});
const event = { event: 'whatsapp_click', path: '/', source: 'facebook' };
function req(payload = event, headers = {}) {
  return new Request('https://jardinesdelencanto.site/api/landing/analytics', {
    method: 'POST', headers: { origin: process.env.CRM_ORIGIN, 'content-type': 'application/json', 'user-agent': 'Mozilla/5.0 Test Browser', ...headers },
    body: typeof payload === 'string' ? payload : JSON.stringify(payload),
  });
}
test('tracker only accepts approved public paths and normalized acquisition sources', () => {
  assert.deepEqual(analyticsContext('/', '?utm_source=fb&phone=573000000000', 'https://evil.invalid/path?token=private'), { path: '/', source: 'facebook' });
  assert.equal(analyticsContext('/crm', '', ''), null);
  assert.equal(analyticsContext('/login', '', ''), null);
  assert.equal(analyticsContext('/unknown', '', ''), null);
  assert.equal(analyticsContext('/', '', 'https://l.instagram.com/private').source, 'instagram');
  assert.equal(analyticsContext('/', '', 'https://facebook.com.evil.invalid').source, 'other');
  assert.equal(analyticsContext('/', '', '').source, 'direct');
  assert.equal(classifyAnalyticsClick('https://wa.me/573008348478?text=private', false), 'whatsapp_click');
  assert.equal(classifyAnalyticsClick('https://chat.whatsapp.com/private', false), 'group_click');
  assert.equal(classifyAnalyticsClick('#plano', false), 'plan_open');
  assert.equal(classifyAnalyticsClick('', true), 'registration_open');
  assert.equal(classifyAnalyticsClick('https://evil.invalid', false), null);
});
test('collector validates origin, content, schema, paths and bounded body before provider', async () => {
  assert.equal((await POST(req(event, {origin:'https://evil.invalid'}))).status, 403);
  assert.equal((await POST(req(event, {'content-type':'text/plain'}))).status, 415);
  for (const payload of [{...event, phone:'private'}, {...event,path:'/crm'}, {...event,event:'lead_registered'}, {...event,source:'raw@email.invalid'}, {...event,path:'/?phone=private'}, [], null, '{']) {
    assert.equal((await POST(req(payload))).status, 422);
  }
  assert.equal((await POST(req('x'.repeat(1025)))).status, 413);
  assert.equal(calls.length, 0);
});
test('collector sends only minimal allowlisted fields, strips session and never exposes provider output', async () => {
  const r = await POST(req());
  assert.equal(r.status, 204);
  assert.equal(await r.text(), '');
  assert.equal(r.headers.get('cache-control'), 'no-store, private');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://umami:3000/api/send');
  assert.deepEqual(calls[0].options.headers, {'Content-Type':'application/json','User-Agent':'Mozilla/5.0 Test Browser'});
  assert.equal(calls[0].options.redirect, 'error');
  assert.equal(calls[0].options.credentials, 'omit');
  const body = JSON.parse(calls[0].options.body);
  assert.deepEqual(body, {type:'event',payload:{website:process.env.UMAMI_WEBSITE_ID,hostname:'jardinesdelencanto.site',url:'/?utm_source=facebook',title:'Jardines del Encanto',name:'whatsapp_click'}});
});
test('pageviews have no custom event name and privacy preferences/admin visits are excluded', async () => {
  await POST(req({...event,event:'page_view'}));
  assert.equal('name' in JSON.parse(calls[0].options.body).payload, false);
  calls=[];
  for (const headers of [{DNT:'1'}, {'Sec-GPC':'1'}, {cookie:'__Host-jardines_session=private'}, {'user-agent':'Googlebot'}]) {
    assert.equal((await POST(req(event,headers))).status,204);
  }
  assert.equal(calls.length,0);
});
test('configuration returns a boolean only; disabled analytics never contacts provider', async () => {
  assert.deepEqual(await (await GET()).json(), {enabled:true});
  process.env.UMAMI_ENABLED='0';
  assert.deepEqual(await (await GET()).json(), {enabled:false});
  assert.equal((await POST(req())).status,204);
  assert.equal(calls.length,0);
});
test('missing trusted client IP, invalid configuration and upstream failure fail without revealing secrets', async () => {
  process.env.UMAMI_TRUST_PROXY='1';
  assert.equal((await POST(req())).status,204);
  assert.equal(calls.length,0);
  await POST(req(event, {'x-real-ip':'203.0.113.10','x-forwarded-for':'evil'}));
  assert.equal(calls[0].options.headers['X-Forwarded-For'],'203.0.113.10');
  assert.equal(calls[0].options.headers['x-forwarded-for'],undefined);
  process.env.UMAMI_TRUST_PROXY='0';
  globalThis.fetch=async()=>{ throw Error('secret'); };
  const r=await POST(req());
  assert.equal(r.status,503);
  assert.deepEqual(await r.json(),{detail:'analytics_unavailable'});
});
