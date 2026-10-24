/* "Your Chrome" mode: HA's AI assistants run in tabs of this Chrome, using its sign-ins.
   HA asks through the native helper; this connects to HA's local relay and carries
   DevTools commands for the tabs HA opened, all in one window of their own.
   Tabs outside that window are never attached or read. */
'use strict';
const RELAY_HOST = 'com.hivemindassembly.connection_helper';
const haTabs = new Set();
let relaySocket = null, relayUrl = null, nativePort = null, haWindowId = null, keepAlive = null;

function relaySend(message) {
  if (relaySocket?.readyState === WebSocket.OPEN) relaySocket.send(JSON.stringify(message));
}

async function haWindow(url) {
  if (haWindowId !== null) {
    try { await chrome.windows.get(haWindowId); return null; } catch { haWindowId = null; }
  }
  const win = await chrome.windows.create({url, focused: false, type: 'normal'});
  haWindowId = win.id;
  await chrome.storage.session.set({haWindowId});
  return win.tabs[0];
}

async function targetIdFor(tabId) {
  const targets = await chrome.debugger.getTargets();
  return targets.find(t => t.tabId === tabId)?.id;
}

async function createTab(url) {
  let tab = await haWindow(url);
  if (!tab) tab = await chrome.tabs.create({windowId: haWindowId, url, active: false});
  await chrome.debugger.attach({tabId: tab.id}, '1.3');
  haTabs.add(tab.id);
  return {tabId: tab.id, targetId: await targetIdFor(tab.id), url: tab.url || url, title: tab.title || ''};
}

async function handle(message) {
  switch (message.op) {
    case 'createTab': return createTab(message.url || 'about:blank');
    case 'closeTab':
      haTabs.delete(message.tabId);
      await chrome.tabs.remove(message.tabId).catch(() => {});
      return {};
    case 'activateTab': {
      const tab = await chrome.tabs.update(message.tabId, {active: true});
      await chrome.windows.update(tab.windowId, {focused: true, drawAttention: true});
      return {};
    }
    case 'cdp': {
      if (!haTabs.has(message.tabId)) throw new Error('Not an HA tab');
      const target = message.sessionId ? {tabId: message.tabId, sessionId: message.sessionId} : {tabId: message.tabId};
      return (await chrome.debugger.sendCommand(target, message.method, message.params || {})) || {};
    }
    case 'removeDownload':
      await chrome.downloads.removeFile(message.downloadId).catch(() => {});
      await chrome.downloads.erase({id: message.downloadId}).catch(() => {});
      return {};
  }
  throw new Error('Unknown request');
}

async function closeOldTabs() {
  // A new HA session starts clean: tabs from an earlier connection are closed.
  for (const tabId of [...haTabs]) {
    haTabs.delete(tabId);
    await chrome.debugger.detach({tabId}).catch(() => {});
    await chrome.tabs.remove(tabId).catch(() => {});
  }
}

function connectRelay(url) {
  if (!url || (relaySocket && relayUrl === url && relaySocket.readyState <= WebSocket.OPEN)) return;
  relaySocket?.close();
  relayUrl = url;
  const ws = new WebSocket(url);
  relaySocket = ws;
  ws.onopen = async () => {
    await closeOldTabs();
    clearInterval(keepAlive);
    keepAlive = setInterval(() => relaySend({event: 'ping'}), 20000);
  };
  ws.onmessage = async event => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.event === 'pong' || message.id === undefined) return;
    try {
      relaySend({id: message.id, result: await handle(message)});
    } catch (error) {
      relaySend({id: message.id, error: String(error?.message || error)});
    }
  };
  ws.onclose = () => {
    if (relaySocket === ws) { relaySocket = null; relayUrl = null; clearInterval(keepAlive); }
  };
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (haTabs.has(source.tabId)) relaySend({event: 'cdp', tabId: source.tabId, sessionId: source.sessionId, method, params});
});
chrome.debugger.onDetach.addListener(source => {
  if (haTabs.delete(source.tabId)) relaySend({event: 'detached', tabId: source.tabId});
});
chrome.tabs.onRemoved.addListener(tabId => {
  if (haTabs.delete(tabId)) relaySend({event: 'detached', tabId});
});
chrome.downloads.onCreated.addListener(item => {
  if (relaySocket) relaySend({event: 'download', kind: 'begin', downloadId: item.id, url: item.finalUrl || item.url,
    suggested: (item.filename || '').split(/[\\/]/).pop()});
});
chrome.downloads.onChanged.addListener(async delta => {
  if (!relaySocket || !delta.state) return;
  if (delta.state.current === 'complete') {
    const [item] = await chrome.downloads.search({id: delta.id});
    relaySend({event: 'download', kind: 'done', downloadId: delta.id, filename: item?.filename || ''});
  } else if (delta.state.current === 'interrupted') {
    relaySend({event: 'download', kind: 'failed', downloadId: delta.id});
  }
});

/* The native helper tells this extension when HA wants to use Chrome (and where). */
function watchHA() {
  if (nativePort) return;
  try {
    nativePort = chrome.runtime.connectNative(RELAY_HOST);
  } catch { nativePort = null; return; }
  nativePort.onMessage.addListener(message => {
    if (message?.op === 'relay') {
      if (message.url) connectRelay(message.url);
      else { relaySocket?.close(); }
    }
  });
  nativePort.onDisconnect.addListener(() => { nativePort = null; });
  nativePort.postMessage({op: 'watch'});
}
chrome.storage.session.get('haWindowId').then(v => { if (Number.isInteger(v.haWindowId)) haWindowId = v.haWindowId; });
chrome.runtime.onStartup.addListener(watchHA);
chrome.runtime.onInstalled.addListener(watchHA);
chrome.alarms.create('ha-watch', {periodInMinutes: 1});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === 'ha-watch') watchHA(); });
watchHA();
globalThis.__haConnectRelay = connectRelay;  // used by HA's automated tests
