'use strict';
const HOST = 'com.hivemindassembly.connection_helper';
const statusBox = document.getElementById('status');
function show(message, error = false) {statusBox.textContent = message; statusBox.classList.toggle('error', error);}
function pageURL(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url : null;}
  catch {return null;}
}
function pageProvider(url) {
  return url?.host === 'claude.ai' ? 'Claude' : ['chatgpt.com', 'chat.openai.com'].includes(url?.host) ? 'ChatGPT' : null;
}
function checkDetails(value, provider) {
  const endpoint = pageURL(value?.endpoint), origin = pageURL(value?.origin);
  if (!endpoint || !origin || value.origin !== origin.origin || endpoint.origin !== origin.origin ||
      endpoint.pathname !== '/mcp' || endpoint.search || endpoint.hash || value.provider !== provider ||
      typeof value.name !== 'string' || typeof value.description !== 'string')
    throw new Error('HA has no valid address. Start the browser connection in HA, then retry.');
  return value;
}
async function native(message) {
  // HA may need a moment to start its connection; it says so and the helper waits.
  for (let attempt = 0; attempt < 60; attempt++) {
    let result;
    try {result = await chrome.runtime.sendNativeMessage(HOST, message);}
    catch {throw new Error('Can\'t reach HA. Make sure HA is running, then try again.');}
    if (!result?.ok) throw new Error(result?.error || 'HA did not answer.');
    if (!result.value?.retry) return result.value;
    show(result.value.message || 'Starting HA\'s connection…');
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  throw new Error('HA\'s connection didn\'t start. Check HA\'s Settings page, then try again.');
}
async function onPage(tabId, operation, data, replace) {
  const result = await chrome.scripting.executeScript({target: {tabId}, func: async (op, payload, overwrite) => {
    try {
      const api = globalThis.__haFormHelper;
      return {ok: true, value: op === 'probe' ? api.probe() : op === 'pair' ? await api.fillPair(payload) : await api.fill(payload, overwrite)};
    } catch (e) {return {ok: false, error: e.message || 'The page could not be filled.'};}
  }, args: [operation, data ?? null, Boolean(replace)]});
  if (!result?.[0]?.result?.ok) throw new Error(result?.[0]?.result?.error || 'The page is unavailable.');
  return result[0].result.value;
}
let readyDetails = null, generation = 0;
async function fill() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id || !pageURL(tab.url)) throw new Error('Open the ChatGPT or Claude setup tab, or HA\'s approval page, and click the helper there.');
  if (tab.status === 'loading') throw new Error('The page is loading. Try again when it finishes.');
  await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['form.js']});
  const page = await onPage(tab.id, 'probe');
  if (page.kind === 'unsupported' || page.kind === 'provider') throw new Error(page.note);
  if (!['ChatGPT', 'Claude'].includes(page.provider)) throw new Error('This approval page is not from ChatGPT or Claude.');
  const details = checkDetails(await native({op: 'details', provider: page.provider}), page.provider);
  let result;
  if (page.kind === 'pairing') {
    const approval = pageURL(page.page_url);
    if (!approval || approval.pathname !== '/authorize' || approval.origin !== details.origin)
      throw new Error('This is not HA\'s current approval page. Start the connection again.');
    const code = await native({op: 'pair', provider: page.provider, page_url: page.page_url, flow: page.flow});
    result = await onPage(tab.id, 'pair', code);
  } else result = await onPage(tab.id, 'fill', details, document.getElementById('replace').checked);
  show('Filled. ' + result.next + (result.warnings.length ? '\n' + result.warnings.join(' ') : ''));
}
let busy = false;
async function run(operation, message = 'Checking HA…') {
  if (busy) return;
  busy = true;
  for (const b of document.querySelectorAll('button')) b.disabled = true;
  for (const a of document.querySelectorAll('nav a')) a.setAttribute('aria-disabled', 'true');
  show(message);
  try {await operation();} catch (e) {show(e?.message || 'The helper could not finish.', true);}
  finally {
    busy = false;
    for (const b of document.querySelectorAll('button')) b.disabled = false;
    for (const a of document.querySelectorAll('nav a')) a.removeAttribute('aria-disabled');
  }
}
document.getElementById('fill').addEventListener('click', () => {
  const d = readyDetails, wants = document.getElementById('auto-pair').checked;
  run(async () => {
    // Chrome only shows the permission prompt during the click, so ask before any other wait.
    let granted = false;
    if (wants && d) {
      try {granted = await chrome.permissions.request({origins: [d.origin + '/*']});} catch { /* optional */ }
    }
    if (granted) {
      const reply = await chrome.runtime.sendMessage({op: 'arm_pairing', provider: d.provider, origin: d.origin});
      if (!reply?.ok) throw new Error(reply?.error || 'Automatic codes could not be turned on.');
    }
    await fill();
    if (wants && !granted) show(statusBox.textContent + '\nOn HA\'s approval page, click the helper to fill the code.');
  });
});
const ago = t => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - t));
  return s < 60 ? 'just now' : s < 3600 ? Math.round(s / 60) + ' min ago' : Math.round(s / 3600) + ' h ago';
};
function summary(e = {}) {
  if (e.last_tool_at) return 'connected, last used HA ' + ago(e.last_tool_at);
  if (e.tools_listed_at) return 'connected';
  if (e.authorized) return 'approved, waiting for it to contact HA';
  if (e.approval_requested_at) return 'waiting for approval';
  return 'not connected';
}
document.getElementById('check').addEventListener('click', () => run(async () => {
  const s = await native({op: 'status'});
  show((s.state === 'ready' ? 'HA browser connection is on.' : 'HA browser connection is ' + (s.state || 'off') + '.') + '\n' +
    ['ChatGPT', 'Claude'].map(p => p + ': ' + summary(s.services?.[p])).join('\n'));
}, 'Checking HA…'));
async function prefetch() {
  const mine = ++generation;
  readyDetails = null;
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const provider = pageProvider(pageURL(tab?.url));
    if (!tab?.id || !provider || tab.status === 'loading') return;
    const details = checkDetails(await native({op: 'details', provider}), provider);
    const [current] = await chrome.tabs.query({active: true, currentWindow: true});
    if (mine === generation && current?.id === tab.id && current.url === tab.url) readyDetails = details;
  } catch { /* Fill reports the problem. */ }
}
async function prepare(provider) {
  readyDetails = null; ++generation;
  const reply = await chrome.runtime.sendMessage({op: 'prepare_setup', ...(provider ? {provider} : {})});
  if (!reply?.ok) throw new Error(reply?.error || 'Reload the helper on chrome://extensions, then retry.');
  show(reply.value.note, reply.value.state === 'blocked');
  if (reply.value.state !== 'ready') return;
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  const url = pageURL(tab?.url);
  if (!tab?.id || !url || tab.status === 'loading') return;
  if (url.pathname === '/authorize') {
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ['form.js']});
    if ((await onPage(tab.id, 'probe')).kind === 'pairing') await fill();
  } else await prefetch();
}
for (const [id, provider] of [['open-chatgpt', 'ChatGPT'], ['open-claude', 'Claude']]) {
  document.getElementById(id).addEventListener('click', event => {
    event.preventDefault();
    run(() => prepare(provider), 'Opening ' + provider + ' connector setup…');
  });
}
run(() => prepare(), 'Opening setup…');
