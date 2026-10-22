// Runs the permanent-address Worker against in-memory stand-ins for Cloudflare's storage and socket.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {HaBridge}=await import(pathToFileURL(process.argv[2]).href);
const store=new Map();
const storage={get:async k=>store.get(k),put:async(k,v)=>{store.set(k,v)},delete:async k=>{(Array.isArray(k)?k:[k]).forEach(x=>store.delete(x))},
 list:async({prefix=''}={})=>new Map([...store].filter(([k])=>k.startsWith(prefix))),getAlarm:async()=>1,setAlarm:async()=>{},
 transaction:async fn=>fn(storage)};
const ws={readyState:1,sent:[],send(t){this.sent.push(JSON.parse(t))}};
const ctx={storage,getWebSockets:()=>[ws],acceptWebSocket(){},setWebSocketAutoResponse(){}};
const O='https://ha-connection-0123456789ab.me.workers.dev';
const b=new HaBridge(ctx,{PUBLIC_ORIGIN:O,DEVICE_KEY:'dk'});
const req=(m,p,{body,headers={}}={})=>b.fetch(new Request(O+p,{method:m,body,headers}));
const cb='https://claude.ai/api/mcp/auth_callback';
let r=await req('POST','/register',{body:JSON.stringify({redirect_uris:[cb]}),headers:{'Content-Type':'application/json'}});
const client=(await r.json()).client_id;
const verifier='v'.repeat(64);
const ch=btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))))).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
r=await req('GET','/authorize?'+new URLSearchParams({client_id:client,redirect_uri:cb,response_type:'code',code_challenge:ch,code_challenge_method:'S256',scope:'ha.projects offline_access',state:'s'}));
const page=await r.text();assert.equal(r.status,200);assert.ok(page.includes('Connect Hivemind Assembly')&&page.includes('ha-pair-status'));
const flow=page.match(/name="flow" value="([^"]+)"/)[1];
r=await req('POST','/device/pair',{body:JSON.stringify({code:'abcdefghijkl',flow,client_id:client,redirect_uri:cb}),headers:{Authorization:'Bearer dk','Content-Type':'application/json'}});
assert.deepEqual(await r.json(),{expires_in:600,flow_verified:true});
r=await req('POST','/authorize',{body:new URLSearchParams({flow,pairing_code:'abcdefghijkl'}),headers:{'Content-Type':'application/x-www-form-urlencoded',Origin:O}});
assert.equal(r.status,303);const loc=new URL(r.headers.get('Location'));assert.equal(loc.origin+loc.pathname,cb);
r=await req('POST','/token',{body:new URLSearchParams({grant_type:'authorization_code',code:loc.searchParams.get('code'),client_id:client,redirect_uri:cb,code_verifier:verifier}),headers:{'Content-Type':'application/x-www-form-urlencoded'}});
const tok=await r.json();assert.equal(tok.scope,'ha.projects offline_access');assert.ok(tok.access_token);
const p=req('POST','/mcp',{body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/list'}),headers:{Authorization:'Bearer '+tok.access_token,'Content-Type':'application/json'}});
await new Promise(s=>setTimeout(s,20));
const sent=ws.sent.at(-1);b.webSocketMessage(ws,JSON.stringify({id:sent.id,type:'part',index:0,total:1,text:JSON.stringify({jsonrpc:'2.0',id:1,result:{tools:[]}})}));
r=await p;assert.deepEqual(await r.json(),{jsonrpc:'2.0',id:1,result:{tools:[]}});
r=await req('GET','/device/status',{headers:{Authorization:'Bearer dk'}});const st=await r.json();
assert.ok(st.connected&&st.services.Claude.authorized&&st.services.Claude.tools_listed_at&&st.services.Claude.approval_requested_at);
r=await req('POST','/mcp',{body:'{}',headers:{'Content-Type':'application/json'}});assert.equal(r.status,401);
console.log('Worker check passed: register, approval page, owner code, consent, token, MCP relay, status.');
