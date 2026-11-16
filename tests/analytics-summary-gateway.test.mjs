import assert from 'node:assert/strict';
import { test, beforeEach, afterEach } from 'node:test';
import { GET, POST } from '../apps/web/app/api/crm/[...path]/route.ts';
const realFetch=globalThis.fetch, oldBase=process.env.API_BASE_URL;
let calls;
beforeEach(()=>{ calls=[];process.env.API_BASE_URL='http://private-api:8000';globalThis.fetch=async(url,options)=>{calls.push({url,options});return Response.json({status:'not_configured'});};});
afterEach(()=>{globalThis.fetch=realFetch;if(oldBase===undefined)delete process.env.API_BASE_URL;else process.env.API_BASE_URL=oldBase;});
const context={params:Promise.resolve({path:['analytics','summary']})};
function request(query='',method='GET'){
 const r=new Request('https://jardinesdelencanto.site/api/crm/analytics/summary'+query,{method});
 Object.defineProperty(r,'cookies',{value:{get:name=>name==='__Host-jardines_session'?{name,value:'session-private'}:undefined}});return r;
}
test('summary gateway only forwards bounded read filters and existing session',async()=>{
 const r=await GET(request('?days=30'),context);
 assert.equal(r.status,200);assert.equal(r.headers.get('cache-control'),'no-store, private');assert.equal(r.headers.get('content-type'),'application/json');
 assert.equal(calls[0].url,'http://private-api:8000/crm/analytics/summary?days=30');
 assert.equal(calls[0].options.headers.get('cookie'),'__Host-jardines_session=session-private');
 assert.equal(calls[0].options.headers.has('authorization'),false);
 assert.equal(calls[0].options.redirect,'error');
 for(const query of ['?days=31','?days=7&days=30','?token=private','?days=7&url=https://evil.invalid'])assert.equal((await GET(request(query),context)).status,422);
 assert.equal((await POST(request('','POST'),context)).status,404);
 assert.equal(calls.length,1);
});
test('summary gateway defaults to7 and bounds/sanitizes provider-independent response errors',async()=>{
 await GET(request(),context);assert.equal(calls[0].url.endsWith('?days=7'),true);
 globalThis.fetch=async()=>new Response('x'.repeat(65537),{headers:{'Content-Type':'application/json'}});
 assert.equal((await GET(request(),context)).status,502);
 globalThis.fetch=async()=>Response.json({detail:'secret upstream token'},{status:500});
 const r=await GET(request(),context);assert.equal(r.status,503);assert.deepEqual(await r.json(),{detail:'analytics_unavailable'});
 globalThis.fetch=async()=>Response.json({detail:'internal'},{status:401});
 assert.equal((await GET(request(),context)).status,401);
});
