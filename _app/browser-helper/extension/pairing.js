/* Runs only on HA's current approval page, after you allow it. Fills the code; never approves. */
(async () => {
  const page = globalThis.__haFormHelper?.probe();
  if (page?.kind !== 'pairing' || globalThis.__haPairingStarted) return;
  globalThis.__haPairingStarted = true;
  const hint = document.getElementById('ha-pair-status');
  try {
    if (hint) hint.textContent = 'Getting the approval code from HA…';
    const reply = await chrome.runtime.sendMessage({op: 'pair_from_page', provider: page.provider, page_url: page.page_url, flow: page.flow});
    if (!reply?.ok) throw new Error(reply?.error || 'Click the HA helper to fill the code.');
    await globalThis.__haFormHelper.fillPair(reply.value);
  } catch (e) {
    if (hint) hint.textContent = e.message || 'Click the HA helper to fill the code.';
  }
})();
