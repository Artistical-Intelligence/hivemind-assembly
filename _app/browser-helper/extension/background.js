/* Opens the ChatGPT/Claude connector form after a toolbar click, and fills HA's approval
   code automatically on the one HA address you allowed. Never submits or approves. */
'use strict';
const SETUP = Object.freeze({ChatGPT: 'https://chatgpt.com/plugins', Claude: 'https://claude.ai/new#customize/connectors'});
const HOST = 'com.hivemindassembly.connection_helper';
const active = new Map();
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

function pageURL(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u : null;}
  catch {return null;}
}
function providerFor(url) {
  const u = pageURL(url);
  return u?.host === 'chatgpt.com' ? 'ChatGPT' : u?.host === 'claude.ai' ? 'Claude' : null;
}
function sameSetup(url, provider) {
  const u = pageURL(url), target = pageURL(SETUP[provider]);
  return Boolean(u && target && u.origin === target.origin &&
    u.pathname.replace(/\/$/, '') === target.pathname && u.hash === target.hash);
}
async function execute(tabId, func, files) {
  const result = await chrome.scripting.executeScript(files ? {target: {tabId}, files} : {target: {tabId}, func});
  return result?.[0]?.result;
}
async function probe(tabId) {
  await execute(tabId, null, ['form.js']);
  return execute(tabId, () => globalThis.__haFormHelper.probe());
}
async function openForm(tab, provider) {
  let existing;
  try {existing = await probe(tab.id);} catch { /* still loading; handled below */ }
  if (existing && ['connection', 'authentication', 'pairing'].includes(existing.kind))
    return {state: 'ready', note: 'The ' + (existing.kind === 'pairing' ? 'HA approval' : provider + ' setup') + ' form is open. Click Fill this page.'};
  const target = SETUP[provider];
  if (!sameSetup(tab.url, provider)) await chrome.tabs.update(tab.id, {url: target});
  const deadline = Date.now() + 14000;
  let initialized = false;
  while (Date.now() < deadline) {
    await pause(250);
    const current = await chrome.tabs.get(tab.id);
    // A redirect to sign-in is never followed with clicks.
    if (current.url && !sameSetup(current.url, provider)) {
      if (current.status === 'loading' && current.pendingUrl === target) continue;
      return {state: 'manual', note: 'Sign in first, then click the helper again.'};
    }
    if (current.status === 'loading') continue;
    try {
      await execute(tab.id, null, ['form.js', 'navigation.js']);
      if (!initialized) {await execute(tab.id, () => globalThis.__haSetupNavigator.reset()); initialized = true;}
      const r = await execute(tab.id, () => globalThis.__haSetupNavigator.step());
      if (r?.state === 'ready' || r?.state === 'blocked') return r;
    } catch (e) {
      if (!/frame|context|loading|removed|cannot access/i.test(String(e.message))) throw e;
    }
  }
  return {state: 'manual', note: 'Open ' + (provider === 'ChatGPT' ? 'Plugins → + → Add custom MCP server' : 'Add → Add custom connector') +
    ' yourself, then click Fill this page.'};
}
async function prepare(message) {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id) return {state: 'choose', note: 'Choose ChatGPT or Claude.'};
  const currentProvider = providerFor(tab.url);
  if (message.provider && !Object.hasOwn(SETUP, message.provider)) throw new Error('Choose ChatGPT or Claude.');
  if (message.provider && message.provider !== currentProvider) {
    await chrome.tabs.create({url: SETUP[message.provider], active: true});
    return {state: 'opened', note: message.provider + ' settings opened in a new tab. Click the helper again in that tab.'};
  }
  if (!currentProvider) {
    try {
      if (pageURL(tab.url)?.pathname === '/authorize') {
        const page = await probe(tab.id);
        if (page?.kind === 'pairing') return {state: 'ready', note: 'Filling the approval code…'};
      }
    } catch { /* no access to unrelated tabs */ }
    return {state: 'choose', note: 'Choose ChatGPT or Claude.'};
  }
  if (active.has(tab.id)) return active.get(tab.id);
  const task = openForm(tab, currentProvider).finally(() => active.delete(tab.id));
  active.set(tab.id, task);
  return task;
}

async function localHA(message) {
  const reply = await chrome.runtime.sendNativeMessage(HOST, message);
  if (!reply?.ok) throw new Error(reply?.error || 'HA is not reachable.');
  return reply.value;
}
const pairRequests = new Map();
async function armPairing(message) {
  const requested = pageURL(message.origin);
  if (!requested || requested.origin !== message.origin) throw new Error('HA has no valid address. Start the connection in HA.');
  const current = await localHA({op: 'details', provider: message.provider});
  if (current?.origin !== message.origin) throw new Error('The HA address changed. Fill the form again.');
  if (!await chrome.permissions.contains({origins: [message.origin + '/*']})) throw new Error('Allow this HA address for automatic codes.');
  await chrome.scripting.unregisterContentScripts({ids: ['ha-pair']}).catch(() => {});
  await chrome.storage.local.set({pairOrigin: message.origin});
  await chrome.scripting.registerContentScripts([{id: 'ha-pair', matches: [message.origin + '/authorize*'],
    js: ['form.js', 'pairing.js'], runAt: 'document_idle', allFrames: false, persistAcrossSessions: true}]);
  return {enabled: true};
}
async function autoPair(message, sender) {
  if (!sender.tab?.id || sender.frameId !== 0 || !sender.url || message.page_url !== sender.url) throw new Error('Unsupported approval page.');
  const u = pageURL(sender.url);
  if (!u || u.pathname !== '/authorize' || u.hash) throw new Error('Unsupported approval page.');
  const {pairOrigin} = await chrome.storage.local.get('pairOrigin');
  if (pairOrigin !== u.origin) throw new Error('Automatic codes are not allowed for this address.');
  if (!['ChatGPT', 'Claude'].includes(message.provider) || typeof message.flow !== 'string') throw new Error('Unknown approval request.');
  if (pairRequests.has(message.flow)) return pairRequests.get(message.flow);
  const request = localHA({op: 'pair', provider: message.provider, page_url: sender.url, flow: message.flow});
  pairRequests.set(message.flow, request);
  setTimeout(() => pairRequests.delete(message.flow), 60000);
  try {return await request;} catch (e) {pairRequests.delete(message.flow); throw e;}
}

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id || !message) return false;
  const fromPopup = sender.url === chrome.runtime.getURL('popup.html') && !sender.tab;
  let task;
  if (message.op === 'prepare_setup' && fromPopup) task = prepare(message);
  else if (message.op === 'arm_pairing' && fromPopup) task = armPairing(message);
  else if (message.op === 'pair_from_page' && sender.tab && sender.frameId === 0) task = autoPair(message, sender);
  else return false;
  task.then(value => reply({ok: true, value}), error => reply({ok: false, error: error.message || 'The helper could not finish.'}));
  return true;
});
