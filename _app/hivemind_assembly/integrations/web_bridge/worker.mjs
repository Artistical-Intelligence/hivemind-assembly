/* Hivemind Assembly permanent connection. Cloudflare Workers Free + SQLite Durable Objects.
 * No paid services, AI endpoints, file storage, external fetches, or public file routes.
 * A single outbound authenticated WebSocket carries bounded MCP requests/results.
 */
const MAX_BODY = 128 * 1024;
const MAX_RESULT = 6 * 1024 * 1024;
const enc = new TextEncoder();
const now = () => Math.floor(Date.now() / 1000);
const token = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), x => x.toString(16).padStart(2, '0')).join('');
const b64url = bytes => btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
const digest = async s => b64url(new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(s))));
const json = (data, status=200, headers={}) => new Response(JSON.stringify(data), {status, headers:{
  'Content-Type':'application/json', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff', ...headers}});
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function same(a,b) { if (typeof a!=='string'||typeof b!=='string'||a.length!==b.length) return false;
  let d=0;for(let i=0;i<a.length;i++)d|=a.charCodeAt(i)^b.charCodeAt(i);return d===0; }
function fail(message, status=400) { const e=new Error(message); e.status=status; throw e; }
async function body(req, form=false) {
  const reader=req.body?.getReader(); let chunks=[],size=0;
  if(reader)while(true){const {done,value}=await reader.read();if(done)break;
    size+=value.byteLength;if(size>MAX_BODY){await reader.cancel();fail('Request too large',413);}chunks.push(value);}
  const bytes=new Uint8Array(size);let at=0;for(const c of chunks){bytes.set(c,at);at+=c.byteLength;}
  const raw=new TextDecoder().decode(bytes);
  try { return form ? Object.fromEntries(new URLSearchParams(raw)) : JSON.parse(raw); }
  catch { fail('Invalid request body'); }
}
function safeRedirect(value) {
  try { const u=new URL(value);
    if(u.protocol!=='https:'||u.username||u.password||u.hash||u.search)return false;
    if(['claude.ai','claude.com'].includes(u.host))return u.pathname==='/api/mcp/auth_callback';
    if(['chatgpt.com','chat.openai.com'].includes(u.host))return ['/connector_platform_oauth_redirect','/connector_platform/oauth_redirect'].includes(u.pathname)||/^\/connector\/oauth\/[A-Za-z0-9_-]{1,160}$/.test(u.pathname);
    return false;
  } catch { return false; }
}
function html(text, status=200, callback='') {return new Response(text,{status,headers:{'Content-Type':'text/html; charset=utf-8',
  'Cache-Control':'no-store','Referrer-Policy':'same-origin','X-Frame-Options':'DENY',
  'Content-Security-Policy':`default-src 'none'; style-src 'unsafe-inline'; form-action 'self' ${callback}; frame-ancestors 'none'; base-uri 'none'`}});}

export default {
  async fetch(request, env) {
    // PUBLIC_ORIGIN is pinned by deployment, never derived from an attacker-controlled Host.
    let u;try {u=new URL(request.url);}catch{return json({error:'Invalid URL'},400);}
    if (!env.PUBLIC_ORIGIN || u.origin!==env.PUBLIC_ORIGIN || u.protocol!=='https:')
      return json({error:'Origin mismatch'},403);
    const id=env.BRIDGE.idFromName('private-ha');
    return env.BRIDGE.get(id).fetch(request);
  }
};

export class HaBridge {
  constructor(ctx,env) {
    this.ctx=ctx;this.env=env;this.pending=new Map();
    // Auto-response permits hibernation; no timer continually keeps the object awake.
    if(typeof WebSocketRequestResponsePair!=='undefined')
      ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('ping','pong'));
  }
  async get(key) {
    const value=await this.ctx.storage.get(key);
    if(value?.exp && value.exp<now()){await this.ctx.storage.delete(key);return null;}
    return value||null;
  }
  async put(key,value,ttl) {
    await this.ctx.storage.put(key,{...value,exp:now()+ttl});
    if(!await this.ctx.storage.getAlarm())await this.ctx.storage.setAlarm(Date.now()+86400000);
  }
  async rate(req,kind,limit,window=3600) {
    const address=req.headers.get('CF-Connecting-IP')||'unknown';
    const key='rate:'+kind+':'+await digest(address);
    await this.ctx.storage.transaction(async s=>{
      let x=await s.get(key); if(!x||x.exp<now())x={count:0,exp:now()+window};
      if(x.count>=limit)fail('Rate limit reached',429);
      x.count++;await s.put(key,x);
    });
  }
  async take(key, predicate=()=>true) {
    return this.ctx.storage.transaction(async s=>{
      const value=await s.get(key);
      if(!value||value.exp<now()||!predicate(value))return null;
      await s.delete(key);return value;
    });
  }
  async event(provider, key) {
    if(!['ChatGPT','Claude'].includes(provider))return;
    await this.ctx.storage.transaction(async store=>{
      const name='observed:'+provider, previous=await store.get(name), epoch=(await store.get('epoch'))||0;
      const data=previous?.epoch===epoch?previous:{epoch};
      data[key]=Date.now()/1000;data.exp=now()+31*86400;await store.put(name,data);
    });
  }
  async services() {
    const epoch=await this.epoch(),out={};
    // This owner-initiated check reads actual surviving grants, not a stale flag.
    const grants=[...(await this.ctx.storage.list({prefix:'access:'})).values(),
                  ...(await this.ctx.storage.list({prefix:'refresh:'})).values()];
    for(const provider of ['ChatGPT','Claude']) {
      const events=await this.get('observed:'+provider);
      const authorized=grants.some(g=>g.provider===provider&&g.epoch===epoch&&g.exp>=now());
      out[provider]={...(events?.epoch===epoch?events:{}),authorized};
      delete out[provider].epoch;delete out[provider].exp;delete out[provider].authorized_until;
    }
    return out;
  }
  async epoch(){return (await this.ctx.storage.get('epoch'))||0;}
  device(req) {return !!this.env.DEVICE_KEY && same(req.headers.get('Authorization')||'','Bearer '+this.env.DEVICE_KEY);}
  socket(){return this.ctx.getWebSockets('device').find(x=>x.readyState===1);}
  async access(req) {
    const h=req.headers.get('Authorization')||'';
    if(!h.startsWith('Bearer ')||h.length>1024)return null;
    const item=await this.get('access:'+await digest(h.slice(7)));
    if(!item||item.epoch!==await this.epoch()||item.resource!==this.env.PUBLIC_ORIGIN+'/mcp')return null;
    return item;
  }
  challenge() {return json({error:'Authentication required'},401,{'WWW-Authenticate':
    `Bearer resource_metadata="${this.env.PUBLIC_ORIGIN}/.well-known/oauth-protected-resource/mcp", scope="ha.projects"`});}
  metadata() {
    const o=this.env.PUBLIC_ORIGIN;
    return {issuer:o,authorization_endpoint:o+'/authorize',token_endpoint:o+'/token',registration_endpoint:o+'/register',
      revocation_endpoint:o+'/revoke',response_types_supported:['code'],grant_types_supported:['authorization_code','refresh_token'],
      token_endpoint_auth_methods_supported:['none','client_secret_post','client_secret_basic'],
      code_challenge_methods_supported:['S256'],scopes_supported:['ha.projects','offline_access']};
  }
  async fetch(req) {
    try {
      const u=new URL(req.url),path=u.pathname,o=this.env.PUBLIC_ORIGIN;
      const origin=req.headers.get('Origin');
      if(origin && ![o,'https://chatgpt.com','https://chat.openai.com','https://claude.ai','https://claude.com'].includes(origin))return json({error:'Invalid Origin'},403);
      const length=Number(req.headers.get('Content-Length')||0);
      if(length>MAX_BODY)return json({error:'Request too large'},413);
      if(req.method==='GET'&&['/.well-known/oauth-authorization-server','/.well-known/openid-configuration'].includes(path))
        return json(this.metadata());
      if(req.method==='GET'&&['/.well-known/oauth-protected-resource','/.well-known/oauth-protected-resource/mcp'].includes(path))
        return json({resource:o+'/mcp',authorization_servers:[o],scopes_supported:['ha.projects'],bearer_methods_supported:['header']});
      if(req.method==='GET'&&path==='/health')return json({service:'ha-connection',version:'1.0.0'});
      if(path.startsWith('/device')) {
        if(!this.device(req))return json({error:'Device authentication required'},401);
        if(path==='/device'&&req.headers.get('Upgrade')?.toLowerCase()==='websocket') {
          for(const ws of this.ctx.getWebSockets('device'))ws.close(1000,'Replaced by owner device');
          const pair=new WebSocketPair(),client=pair[0],server=pair[1];
          this.ctx.acceptWebSocket(server,['device']);
          return new Response(null,{status:101,webSocket:client});
        }
        if(path==='/device/pair'&&req.method==='POST') {
          const data=await body(req);if(!/^[A-Za-z0-9_-]{10,64}$/.test(data.code||''))fail('Invalid pairing code');
          let flow=null;
          if(data.flow!==undefined) {
            if(typeof data.flow!=='string'||!/^[A-Za-z0-9_-]{20,100}$/.test(data.flow))fail('Invalid pairing flow');
            flow=await this.get('flow:'+data.flow);
            if(!flow||flow.epoch!==await this.epoch()||flow.client_id!==data.client_id||flow.redirect_uri!==data.redirect_uri)
              fail('The approval page expired or does not match this connection',403);
          }
          await this.put(data.flow?'pair_for:'+data.flow:'pair',{hash:await digest(data.code),flow:data.flow||null},600);
          return json({expires_in:600,flow_verified:!!flow});
        }
        if(path==='/device/revoke'&&req.method==='POST') {
          await this.ctx.storage.put('epoch',(await this.epoch())+1);await this.ctx.storage.delete('pair');
                    return json({revoked:true});
        }
        if(path==='/device/status'&&req.method==='GET')return json({connected:!!this.socket(),services:await this.services()});
        return json({error:'Not found'},404);
      }
      if(path==='/register'&&req.method==='POST')return await this.register(req);
      if(path==='/authorize'&&req.method==='GET')return await this.authorize(req,u);
      if(path==='/authorize'&&req.method==='POST')return await this.consent(req);
      if(path==='/token'&&req.method==='POST')return await this.exchange(req);
      if(path==='/revoke'&&req.method==='POST') {
        const p=await body(req,true);const {client}=await this.clientAuth(req,p);
        const key='refresh:'+await digest(p.token||'');const r=await this.get(key);
        if(r?.client_id===client.client_id)await this.ctx.storage.delete(key);
        const ak='access:'+await digest(p.token||'');const a=await this.get(ak);
        if(a?.client_id===client.client_id)await this.ctx.storage.delete(ak);
        return new Response(null,{status:200});
      }
      if(path==='/mcp') {
        const grant=await this.access(req);if(!grant)return this.challenge();
        if(req.method!=='POST')return json({error:'Stateless JSON MCP uses POST'},405,{'Allow':'POST'});
        const version=req.headers.get('MCP-Protocol-Version');
        if(version&&!['2025-11-25','2025-06-18','2025-03-26','2024-11-05'].includes(version))fail('Unsupported MCP version');
        if(!req.headers.get('Content-Type')?.startsWith('application/json'))fail('application/json required',415);
        await this.rate(req,'mcp',120,60);
        const message=await body(req);
        if(!message||Array.isArray(message)||message.jsonrpc!=='2.0')fail('Invalid JSON-RPC request');
        if(typeof message.method!=='string'||message.method.startsWith('_ha_'))return json({jsonrpc:'2.0',id:message.id??null,error:{code:-32601,message:'Method not found'}},400);
        if(!this.socket())return json({error:'HA is offline. Open Hivemind Assembly on your computer.'},503);
        const id=token(),socket=this.socket();
        if(!Object.hasOwn(message,'id')) {
          socket.send(JSON.stringify({id,message}));return new Response(null,{status:202});
        }
        if(this.pending.size>=12)return json({error:'Bridge is busy; retry later'},429);
        const result=await new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error('HA did not respond in time. Check HA before repeating the request.'));},20000);
          this.pending.set(id,{resolve,reject,timer,parts:[],size:0,total:null,socket});
          try{socket.send(JSON.stringify({id,message}));}catch(e){clearTimeout(timer);this.pending.delete(id);reject(e);}
        });
        const rpc=JSON.parse(result),provider=grant.provider;
        await this.event(provider,'last_request_at');
        if(!rpc.error && !rpc.result?.isError) {
          const stage={'initialize':'initialized_at','tools/list':'tools_listed_at','tools/call':'last_tool_at'}[message.method];
          if(stage)await this.event(provider,stage);
        }
        return new Response(result,{status:200,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
      }
      return json({error:'Not found'},404);
    } catch(e) {
      if(req.method==='POST'&&new URL(req.url).pathname==='/authorize')
        return html('<h1>Connection not completed</h1><p>'+esc(e.status?e.message:'Start the connection again from ChatGPT or Claude.')+'</p><p>No access was granted.</p>',e.status||502);
      return json({error:e.status?e.message:'The connection failed; check the Connections page in HA.'},e.status||502);
    }
  }
  async register(req) {
    await this.rate(req,'register',6);
    const p=await body(req);
    if(!Array.isArray(p.redirect_uris)||!p.redirect_uris.length||p.redirect_uris.length>5||!p.redirect_uris.every(safeRedirect))
      fail('Only exact HTTPS ChatGPT or Claude callback URLs are permitted by this private bridge.');
    const method=p.token_endpoint_auth_method||'none';
    if(!['none','client_secret_post','client_secret_basic'].includes(method))fail('Unsupported client authentication');
    const client_id=token(),client_secret=method==='none'?undefined:token();
    const client={client_id,redirect_uris:p.redirect_uris,client_name:String(p.client_name||(new URL(p.redirect_uris[0]).hostname.startsWith('claude.')?'Claude':'ChatGPT')).slice(0,80),
      token_endpoint_auth_method:method,secret_hash:client_secret?await digest(client_secret):null};
    await this.put('client:'+client_id,client,90*86400);
    return json({client_id,client_secret,client_id_issued_at:now(),client_secret_expires_at:0,
      redirect_uris:client.redirect_uris,grant_types:['authorization_code','refresh_token'],response_types:['code'],
      token_endpoint_auth_method:method},201);
  }
  async authorize(req,u) {
    await this.rate(req,'authorize',60);
    const p=Object.fromEntries(u.searchParams),client=await this.get('client:'+p.client_id);
    if(!client||!client.redirect_uris.includes(p.redirect_uri)||!safeRedirect(p.redirect_uri))fail('Invalid client or redirect URI');
    if(p.response_type!=='code'||p.code_challenge_method!=='S256'||!/^[A-Za-z0-9_-]{43}$/.test(p.code_challenge||''))
      fail('Authorization Code with PKCE S256 is required');
    const resource=p.resource||this.env.PUBLIC_ORIGIN+'/mcp';
    if(resource!==this.env.PUBLIC_ORIGIN+'/mcp')fail('Invalid resource');
    const scope=p.scope||'ha.projects offline_access';
    if(scope.split(' ').some(x=>!['ha.projects','offline_access'].includes(x)))fail('Invalid scope');
    if(!scope.split(' ').includes('ha.projects'))fail('ha.projects scope required');
    const id=token();await this.put('flow:'+id,{client_id:p.client_id,redirect_uri:p.redirect_uri,
      challenge:p.code_challenge,state:String(p.state||'').slice(0,2048),resource,scope,epoch:await this.epoch()},600);
    const provider=new URL(p.redirect_uri).hostname.startsWith('claude.')?'Claude':'ChatGPT';
    await this.event(provider,'approval_requested_at');
    return html(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Approve Hivemind Assembly</title>
<style>body{font:16px system-ui;max-width:520px;margin:6vh auto;padding:24px;line-height:1.5;color:#18241f}h1{font-size:24px}input,button{box-sizing:border-box;width:100%;font:inherit;padding:11px;margin:10px 0;border:1px solid #9fb0a8;border-radius:7px}button{background:#1f5e46;color:#fff;cursor:pointer}small{display:block;color:#56645d}</style>
<h1>Connect Hivemind Assembly</h1><p>${provider} will be able to use the projects you shared in HA's Connections page. Nothing else on your computer is shared.</p>
<form method="post" action="/authorize"><input type="hidden" name="flow" value="${esc(id)}"><label>Approval code<input name="pairing_code" autocomplete="off" maxlength="64" required autofocus></label><small id="ha-pair-status">The HA Chrome helper fills this in. Otherwise, select Show approval code in HA (Connections) and enter it here.</small><button>Approve</button></form>
<small>Only approve a connection you started. You can disconnect it in HA at any time.</small></html>`,200,p.redirect_uri);
  }

  async consent(req) {
    await this.rate(req,'consent',10,600);
    // Cross-site forms are rejected; requests without Origin still need an
    // unguessable flow ID plus the one-use owner code.
    const origin=req.headers.get('Origin');if(origin&&origin!==this.env.PUBLIC_ORIGIN)fail('Invalid consent origin',403);
    const p=await body(req,true),flow=await this.get('flow:'+p.flow);
    if(!flow||flow.epoch!==await this.epoch())fail('Connection request expired');
    const hash=await digest(p.pairing_code||'');
    const pair=await this.take('pair_for:'+p.flow,x=>same(x.hash,hash)) || await this.take('pair',x=>same(x.hash,hash)&&(!x.flow||x.flow===p.flow));
    if(!pair)fail('Invalid or expired pairing code',403);
    await this.ctx.storage.delete('flow:'+p.flow);await this.ctx.storage.delete('pair_for:'+p.flow);
    await this.event(new URL(flow.redirect_uri).hostname.startsWith('claude.')?'Claude':'ChatGPT','approved_at');
    const code=token();await this.put('code:'+await digest(code),flow,120);
    const target=new URL(flow.redirect_uri);target.searchParams.set('code',code);
    if(flow.state)target.searchParams.set('state',flow.state);
    return new Response(null,{status:303,headers:{Location:target.toString(),'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}});
  }
  async clientAuth(req,p) {
    let id=p.client_id,provided=p.client_secret;
    const header=req.headers.get('Authorization')||'';
    if(header.startsWith('Basic ')) {
      let raw;try{raw=atob(header.slice(6));}catch{fail('Invalid client',401);}
      const at=raw.indexOf(':');if(at<0)fail('Invalid client',401);
      id=decodeURIComponent(raw.slice(0,at));provided=decodeURIComponent(raw.slice(at+1));
    }
    const client=await this.get('client:'+id);
    if(!client)fail('Invalid client',401);
    if(client.secret_hash&&!same(client.secret_hash,await digest(provided||'')))fail('Invalid client',401);
    return {client,id};
  }
  async exchange(req) {
    await this.rate(req,'token',120);
    const p=await body(req,true),{client,id}=await this.clientAuth(req,p);
    let grant;
    const resource=p.resource||this.env.PUBLIC_ORIGIN+'/mcp';
    if(resource!==this.env.PUBLIC_ORIGIN+'/mcp')fail('Invalid resource');
    if(p.grant_type==='authorization_code') {
      if(!/^[A-Za-z0-9._~-]{43,128}$/.test(p.code_verifier||''))fail('Invalid PKCE verifier');
      const challenge=await digest(p.code_verifier),epoch=await this.epoch();
      grant=await this.take('code:'+await digest(p.code||''),x=>x.client_id===id&&x.redirect_uri===p.redirect_uri&&
        x.resource===resource&&x.epoch===epoch&&same(x.challenge,challenge));
    } else if(p.grant_type==='refresh_token') {
      const epoch=await this.epoch();
      grant=await this.take('refresh:'+await digest(p.refresh_token||''),x=>x.client_id===id&&x.resource===resource&&x.epoch===epoch);
    } else fail('Unsupported grant type');
    if(!grant)fail('Invalid or expired grant');
    const access_token=token(),refresh_token=token(),epoch=await this.epoch();
    const provider=grant.provider||(new URL(grant.redirect_uri).hostname.startsWith('claude.')?'Claude':'ChatGPT');
    const record={client_id:id,resource,scope:grant.scope||'ha.projects offline_access',epoch,provider};
    await this.put('access:'+await digest(access_token),record,3600);
    await this.put('refresh:'+await digest(refresh_token),record,30*86400);
    await this.event(provider,'token_received_at');
    const observed=await this.get('observed:'+provider)||{epoch};
    await this.put('observed:'+provider,{...observed,authorized_until:Date.now()/1000+30*86400},31*86400);
    return json({access_token,refresh_token,token_type:'Bearer',expires_in:3600,scope:record.scope});
  }
  webSocketMessage(ws,message) {
    if(message==='ping'){ws.send('pong');return;}
    if(typeof message!=='string'||message.length>100000)return;
    let data;try{data=JSON.parse(message);}catch{return;}
    const p=this.pending.get(data.id);if(!p||p.socket!==ws)return;
    if(data.type!=='part'||!Number.isInteger(data.index)||!Number.isInteger(data.total)||data.total<1||data.total>128||
       data.index!==p.parts.length||typeof data.text!=='string'||data.text.length>65536||
       (p.total!==null&&p.total!==data.total))return this.rejectPending(data.id,'Invalid device response');
    p.total=data.total;p.size+=enc.encode(data.text).length;
    if(p.size>MAX_RESULT)return this.rejectPending(data.id,'Response too large; request less at once');
    p.parts.push(data.text);
    if(p.parts.length===p.total) {
      const raw=p.parts.join('');let result;try{result=JSON.parse(raw);}catch{return this.rejectPending(data.id,'Invalid response');}
      if(result.jsonrpc!=='2.0')return this.rejectPending(data.id,'Invalid response');
      clearTimeout(p.timer);this.pending.delete(data.id);p.resolve(raw);
    }
  }
  rejectPending(id,message) {const p=this.pending.get(id);if(p){clearTimeout(p.timer);this.pending.delete(id);p.reject(new Error(message));}}
  webSocketClose(ws,code,reason,wasClean) {
    for(const [id,p] of this.pending)if(p.socket===ws)this.rejectPending(id,'HA disconnected');
    try{ws.close(1000,'Closed');}catch{}
  }
  webSocketError(ws,error) {this.webSocketClose(ws,1011,'Connection lost',false);}
  async alarm() {
    const all=await this.ctx.storage.list({limit:5000});const expired=[];
    for(const [key,value] of all)if(value?.exp&&value.exp<now())expired.push(key);
    if(expired.length)await this.ctx.storage.delete(expired);
    if(all.size>expired.length)await this.ctx.storage.setAlarm(Date.now()+86400000);
  }
}
