// HA integration wrapper. Donor files retain their original MIT license.
import { generateKeyPairSync, randomUUID } from 'node:crypto';
import * as Effect from 'effect/Effect';
import { signRelayJwt, verifyRelayJwt } from './donor/relayJwt.ts';
import { verifyDpopProof } from './donor/dpop.ts';
import { buildConnectAuthorizeRequestUrl } from './donor/connectAuth.ts';
import { clerkFrontendApiUrlFromPublishableKey } from './donor/relayAuth.ts';
import { hasExactScope, hasBoundedCloudProofLifetime } from './donor/linkChecks.ts';

const TYPES = new Set(['t3-env-link+jwt','t3-env-mint+jwt','t3-env-health+jwt','t3-env-managed-tunnel-recovery+jwt']);
const keyPair=()=>generateKeyPairSync('ed25519',{
  privateKeyEncoding:{type:'pkcs8',format:'pem'},publicKeyEncoding:{type:'spki',format:'pem'}
});
function bounded(value:unknown, max:number):string {
  if(typeof value!=='string'||value.length===0||value.length>max) throw new Error('Invalid bounded protocol field');
  return value;
}
async function verify(request:any){
  const health=request.kind==='health';
  if(!health&&request.kind!=='mint')throw new Error('Unsupported cloud proof');
  const now=Math.floor(Date.now()/1000);
  const payload=await Effect.runPromise(verifyRelayJwt({publicKey:bounded(request.publicKey,4096),token:bounded(request.token,32768),
    typ:health?'t3-cloud-health+jwt':'t3-cloud-mint+jwt',issuer:bounded(request.issuer,512),
    audience:'t3-env:'+bounded(request.environmentId,200),nowEpochSeconds:now}));
  if(payload.sub!==request.cloudUserId||payload.environmentId!==request.environmentId||
      !Number.isInteger(payload.iat)||!Number.isInteger(payload.exp)||
      !hasBoundedCloudProofLifetime({iat:payload.iat!,exp:payload.exp!,nowSeconds:now})||
      !Array.isArray(payload.scope)||!hasExactScope({scopes:payload.scope as string[],expected:health?'environment:status':'environment:connect'}))
    throw new Error('Cloud proof scope or identity mismatch');
  bounded(payload.jti,256);bounded(payload.nonce,512);
  if(!health){
    const thumbprint=bounded(payload.clientProofKeyThumbprint,256);
    if((payload.cnf as any)?.jkt!==thumbprint)throw new Error('Cloud proof key binding mismatch');
  }
  return payload;
}
async function main(request:any){
  if(!request||typeof request!=='object')throw new Error('Invalid request');
  switch(request.action){
    case 'keygen': return keyPair();
    case 'authorize': return {url:buildConnectAuthorizeRequestUrl({hostedAppUrl:'https://app.t3.codes',
      state:bounded(request.state,256),challenge:bounded(request.challenge,256),loopbackPort:34338}),
      frontend:clerkFrontendApiUrlFromPublishableKey('pk_live_Y2xlcmsudDMuY29kZXMk')};
    case 'sign':
      if(!TYPES.has(request.typ))throw new Error('Unsupported signing purpose');
      return {proof:await Effect.runPromise(signRelayJwt({privateKey:bounded(request.privateKey,4096),typ:request.typ,payload:request.payload}))};
    case 'verify_cloud': return {payload:await verify(request)};
    case 'verify_dpop': return verifyDpopProof({proof:bounded(request.proof,32768),method:bounded(request.method,20),
      url:bounded(request.url,4096),nowEpochSeconds:Math.floor(Date.now()/1000),
      expectedThumbprint:bounded(request.thumbprint,256),
      ...(request.accessToken?{expectedAccessToken:bounded(request.accessToken,2048)}:{})});
    case 'selftest': {
      const key=keyPair(), now=Math.floor(Date.now()/1000),env='ha-fixture';
      const payload={iss:'https://relay.fixture.invalid',aud:'t3-env:'+env,sub:'fixture-owner',
        jti:randomUUID(),iat:now,exp:now+60,environmentId:env,nonce:randomUUID(),scope:['environment:status']};
      const token=await Effect.runPromise(signRelayJwt({privateKey:key.privateKey,typ:'t3-cloud-health+jwt',payload}));
      const good={kind:'health',token,publicKey:key.publicKey,issuer:payload.iss,environmentId:env,cloudUserId:payload.sub};
      await verify(good);
      let rejected=0;
      for(const bad of [{...good,cloudUserId:'wrong'},{...good,environmentId:'wrong'},{...good,kind:'mint'},{...good,token:token.slice(0,-8)+'AAAAAAAA'}]){
        try{await verify(bad);}catch{rejected++;}
      }
      if(rejected!==4)throw new Error('Protocol negative test failed');
      if(verifyDpopProof({proof:'invalid',method:'POST',url:'https://fixture.invalid',nowEpochSeconds:now}).ok)
        throw new Error('Invalid DPoP was accepted');
      return {passed:true,signature_roundtrip:true,rejected_identity_type_signature:rejected,invalid_dpop_rejected:true};
    }
    default:throw new Error('Unsupported HA connection operation');
  }
}
let size=0;const parts:Buffer[]=[];
try{
  for await(const chunk of process.stdin){size+=chunk.length;if(size>512*1024)throw new Error('Request exceeds limit');parts.push(chunk);}
  const result=await main(JSON.parse(Buffer.concat(parts).toString('utf8')));
  process.stdout.write(JSON.stringify({ok:true,result})+'\n');
}catch{
  // Never serialize keys, tokens, upstream exceptions or stack traces.
  process.stdout.write(JSON.stringify({ok:false,error:'Connection proof or request was not accepted'})+'\n');process.exitCode=1;
}
