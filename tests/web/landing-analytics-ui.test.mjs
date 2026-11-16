import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { createRequire } from 'node:module';
import ts from 'typescript';
const require=createRequire(import.meta.url);
function harness(path='/',search='?utm_source=facebook&phone=private',dnt='0'){
 let effect;
 const cache=new Map();
 function load(file){if(cache.has(file))return cache.get(file).exports;const module={exports:{}};cache.set(file,module);
 const js=ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const req=name=>name==='react'?{useEffect:fn=>{effect=fn;}}:name.startsWith('.')?load(resolve(dirname(file),name)+'.ts'):require(name);
 new Function('require','module','exports',js)(req,module,module.exports);return module.exports;}
 const Component=load(resolve('apps/web/components/landing-analytics.tsx')).LandingAnalytics;
 const names=['fetch','location','document','navigator','Element'],saved=new Map(names.map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)])),calls=[],listeners=new Map();
 for(const [name,value] of Object.entries({location:{pathname:path,search},document:{referrer:'',addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)},navigator:{doNotTrack:dnt},Element:class Element{constructor(target){this.target=target;}closest(){return this.target;}},fetch:async(url,options)=>{calls.push({url,options});return Response.json({enabled:true});}}))Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});
 Component();const cleanup=effect();
 return {calls,listeners,cleanup,restore(){cleanup?.();for(const [name,descriptor]of saved)if(descriptor)Object.defineProperty(globalThis,name,descriptor);else delete globalThis[name];}};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('tracker records one page view and allowlisted clicks without link text, form contents or raw queries',async()=>{
 const h=harness();try{await settle();assert.equal(h.calls.length,2);assert.equal(h.calls[0].url,'/api/landing/analytics/config');
 assert.deepEqual(JSON.parse(h.calls[1].options.body),{path:'/',source:'facebook',event:'page_view'});
 const target={getAttribute:()=> 'https://wa.me/573008348478?text=secret',hasAttribute:()=>false};
 h.listeners.get('click')({target:new Element(target)});await settle();
 assert.deepEqual(JSON.parse(h.calls[2].options.body),{path:'/',source:'facebook',event:'whatsapp_click'});
 assert.equal(h.calls[2].options.keepalive,true);assert.equal(h.calls[2].options.credentials,'same-origin');
 assert.doesNotMatch(h.calls.map(x=>JSON.stringify(x)).join(''),/573008348478|secret|phone=|private/);
 h.cleanup();assert.equal(h.listeners.size,0);
 }finally{h.restore();}
});
test('tracker excludes private routes, respects DNT and cancels unmounted initialization',async()=>{
 for(const [path,dnt]of [['/crm','0'],['/login','0'],['/','1']]){const h=harness(path,'',dnt);try{await settle();assert.equal(h.calls.length,0);assert.equal(h.listeners.size,0);}finally{h.restore();}}
 const h=harness();try{h.cleanup();await settle();assert.equal(h.calls.length,1);assert.equal(h.listeners.size,0);}finally{h.restore();}
});
test('only approved public pages mount the tracker and privacy notice reflects internal measurement',()=>{
 const home=readFileSync('apps/web/app/page.tsx','utf8'),guide=readFileSync('apps/web/app/lotes-acacias-desde-bogota-soacha/page.tsx','utf8');
 assert.match(home,/<LandingAnalytics \/>/);assert.match(guide,/<LandingAnalytics \/>/);
 assert.doesNotMatch(readFileSync('apps/web/app/layout.tsx','utf8'),/LandingAnalytics/);
 assert.match(home,/medición interna está activa/);assert.doesNotMatch(home,/No usamos\s+herramientas de analítica/);
});
