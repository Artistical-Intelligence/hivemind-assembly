/* HA-owned setup, browser automation and private remote-control interface. */
(() => {
  const host = document.getElementById('ha-experience');
  if (!host) return;
  let session = null, snapshot = null, pending = false;
  const q = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  host.innerHTML = `
    <h2>Your HA installation</h2>
    <p>Setup, browser actions, and remote control stay here. Your existing projects, accounts, and histories are retained.</p>
    <div id="ha-capabilities" class="grid"></div>
    <details><summary>Browser automation</summary>
      <p>Use an existing HA browser profile. Credential and verification fields are completed directly in the website.</p>
      <label>Browser profile <select id="ha-auto-profile"></select></label>
      <label>Website <input id="ha-auto-url" type="url" placeholder="https://example.com/settings" autocomplete="off"></label>
      <div class="row"><button id="ha-auto-open">Open setup page</button><button id="ha-auto-read">Read current page</button><button id="ha-auto-close">Close this page</button></div>
      <label>Field or button <select id="ha-auto-ref"><option value="">Read the page first</option></select></label>
      <label>Non-secret setup value <input id="ha-auto-value" autocomplete="off" maxlength="4000"></label>
      <div class="row"><button id="ha-auto-fill">Fill selected field</button><button id="ha-auto-click">Click selected button</button></div>
      <p id="ha-auto-state" role="status">No automation page is open.</p><pre id="ha-auto-result" style="white-space:pre-wrap;max-height:22rem;overflow:auto"></pre>
    </details>
    <details><summary>Remote control</summary>
      <p>Control this HA installation from your phone or another computer through your private Tailscale network. No browser-debugging port is shared.</p>
      <p id="ha-remote-state" role="status"></p>
      <div class="row"><button id="ha-remote-check">Check private connection</button><button id="ha-remote-enable">Enable remote access</button><button id="ha-remote-disable">Disable remote access</button></div>
      <label>Device name <input id="ha-device-name" value="My phone" maxlength="80" autocomplete="off"></label>
      <button id="ha-remote-pair">Pair device</button>
      <div id="ha-pair-result" hidden><p>Open this private link on the named device. It grants control of HA and expires in 30 days. It is not saved in HA's logs.</p><input id="ha-pair-url" readonly aria-label="Private device link"><button id="ha-pair-copy">Copy private link</button></div>
      <div id="ha-devices"></div>
      <p class="muted">Hosted access through T3 Connect remains under integration; the private route does not replace that requested feature.</p>
    </details>
    <details><summary>Implementation and service details</summary>
      <p>HA includes selected Hermes-derived storage/task code, OpenCLI browser-inspection code, and Agent-Reach outcome handling. Their licenses and source records are retained. No independent launch or login-copy step is required for those embedded components.</p>
      <p>Tailscale still requires its supported local network service and account sign-in. Remote pairing is HA-owned and can be revoked below. A configured address is not proof of a successful remote-device test.</p>
    </details>`;

  const message = (text, bad=false) => { q('ha-auto-state').textContent = text; q('ha-auto-state').style.fontWeight = bad ? 'bold' : 'normal'; };
  const execute = async action => {
    if (pending) return;
    pending = true;
    try {
      const data = {action, operation_id: crypto.randomUUID()};
      if (action === 'open') Object.assign(data, {profile:q('ha-auto-profile').value, url:q('ha-auto-url').value});
      else { if (!session) throw new Error('Open a setup page first.'); data.session=session; }
      if (action === 'fill' || action === 'click') Object.assign(data, {snapshot, ref:q('ha-auto-ref').value});
      if (action === 'fill') data.value = q('ha-auto-value').value;
      message('HA is working on the selected page…');
      const reply = await api('automation/command', data);
      if (!reply.ok) throw new Error(reply.error?.message || 'This action needs attention.');
      const item = reply.items?.[0] || {};
      if (action === 'open') { session=item.session; snapshot=null; }
      if (action === 'read') {
        snapshot=item.snapshot;
        q('ha-auto-result').textContent=item.text || '';
        q('ha-auto-ref').innerHTML=(item.controls||[]).map(c=>`<option value="${safe(c.ref)}">${safe(c.ref)} — ${safe(c.label || c.tag)}</option>`).join('');
      } else if (action !== 'open') snapshot=null;
      if (action === 'close') { session=null; q('ha-auto-result').textContent=''; }
      q('ha-auto-value').value='';
      message(action==='read' ? 'Page read. Select the intended field or button.' : action==='close' ? 'Automation page closed.' : 'Step dispatched. Read the page to verify its result.');
    } catch (e) { message(e.message, true); }
    finally { pending=false; }
  };
  for (const action of ['open','read','fill','click','close']) q('ha-auto-'+action).onclick=()=>execute(action);
  for (const action of ['check','enable','disable']) q('ha-remote-'+action).onclick=async()=>{
    try { await api('remote/'+action,{}); notice('HA is checking or updating its private connection.'); await refresh(); }
    catch(e) { notice(e.message,true); }
  };
  q('ha-remote-pair').onclick=async()=>{
    try {
      const r=await api('remote/pair',{label:q('ha-device-name').value,days:30});
      q('ha-pair-url').value=r.url; q('ha-pair-result').hidden=false;
      setTimeout(()=>{q('ha-pair-url').value='';q('ha-pair-result').hidden=true;},120000);
      await refresh();
    } catch(e) { notice(e.message,true); }
  };
  q('ha-pair-copy').onclick=async()=>{
    try { await navigator.clipboard.writeText(q('ha-pair-url').value); notice('Private device link copied.'); }
    catch { q('ha-pair-url').select(); notice('Select and copy the private link.'); }
  };
  q('ha-devices').onclick=async e=>{
    const id=e.target?.dataset?.revoke;
    if (!id) return;
    try { await api('remote/revoke',{device:id}); await refresh(); } catch(err){ notice(err.message,true); }
  };
  window.renderCapabilities = state => {
    const x=state.experience || {}, remote=x.remote || {};
    q('ha-capabilities').innerHTML = `<div><strong>Sessions and tasks</strong><p>${x.state_engine ? 'Built into HA' : 'Needs attention'}</p></div><div><strong>Browser automation</strong><p>${x.automation?.available ? 'Built into HA' : 'Needs attention'}</p></div><div><strong>Analysis</strong><p>${state.foundations?.ready ? 'Configured' : 'Run analysis setup below'}</p></div>`;
    const profiles=x.profiles || [], selected=q('ha-auto-profile').value;
    const key=JSON.stringify(profiles);
    if (q('ha-auto-profile').dataset.profiles !== key) {
      q('ha-auto-profile').innerHTML=profiles.map(p=>`<option value="${safe(p)}">${safe(p)}</option>`).join('');
      if (profiles.includes(selected)) q('ha-auto-profile').value=selected;
      q('ha-auto-profile').dataset.profiles=key;
    }
    const label={unchecked:'Not checked this session',available:'Private network is available',configured:'Configured — verify by opening HA on your remote device',disabled:'Disabled',needs_sign_in:'Private network sign-in required',needs_attention:'Connection needs attention',account_changed:'Network account changed; automatic switching was blocked',configuring:'Configuring private access'}[remote.state] || 'Not configured';
    q('ha-remote-state').textContent=label+(remote.origin ? ' · '+remote.origin : '');
    q('ha-devices').innerHTML=(remote.devices||[]).map(d=>`<p>${safe(d.label)} · expires ${safe(new Date(d.expires*1000).toLocaleDateString())} <button data-revoke="${safe(d.id)}">Revoke</button></p>`).join('');
    q('ha-remote-pair').disabled=remote.state!=='configured';
  };
})();
