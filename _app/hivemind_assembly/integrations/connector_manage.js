/* HA's own assistant windows only: find HA's old connector and the connector form's
   submit button. Marks elements with data-ha-* so Playwright performs real clicks.
   Acts only on a connector named exactly NAME; never touches anything else. */
(() => {
  'use strict';
  const norm = v => String(v || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = el => !!el && el.isConnected && !el.hidden && getComputedStyle(el).display !== 'none' &&
    getComputedStyle(el).visibility !== 'hidden' && el.getClientRects().length > 0;
  const all = (root, sel) => [...root.querySelectorAll(sel)].filter(visible);
  const text = el => norm(el?.innerText || el?.textContent || el?.getAttribute?.('aria-label') || '');
  const clickable = root => all(root, 'button,[role=button],[role=menuitem],a[role=menuitem]')
    .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true');
  const clear = () => document.querySelectorAll('[data-ha-target]').forEach(e => e.removeAttribute('data-ha-target'));
  const mark = el => {clear(); el.setAttribute('data-ha-target', '1'); return true;};

  // The smallest element whose own text is exactly the connector name, then the row around it.
  function rows(name) {
    const wanted = norm(name);
    const labels = all(document, 'h1,h2,h3,h4,span,div,p,a,button').filter(el =>
      text(el) === wanted && ![...el.children].some(c => text(c) === wanted));
    const out = [];
    for (const label of labels) {
      if (label.closest('[role=dialog],[aria-modal=true],dialog,textarea,[contenteditable=true]')) continue;
      let row = label.parentElement;
      for (let i = 0; row && row !== document.body && i < 5; i++, row = row.parentElement) {
        const named = all(row, '*').filter(e => text(e) === wanted && ![...e.children].some(c => text(c) === wanted));
        if (named.length > 1) {row = null; break;}  // grew into a list holding several connectors
        if (clickable(row).length) break;
      }
      if (row && row !== document.body) out.push(row);
    }
    return [...new Set(out)];
  }

  /* One step of removing the old connector. Returns what to click next, or done. */
  function removeStep(name) {
    const menus = all(document, '[role=menu]');
    if (menus.length === 1) {
      const items = clickable(menus[0]).filter(e => ['remove', 'delete', 'uninstall', 'remove connector', 'delete plugin', 'remove plugin'].includes(text(e)));
      if (items.length === 1) return {state: 'click', step: 'menu-remove', ok: mark(items[0])};
      return {state: 'stuck', note: 'The connector menu has no Remove or Delete item.'};
    }
    const dialogs = all(document, '[role=dialog],[aria-modal=true],dialog,[role=alertdialog]');
    if (dialogs.length === 1 && /remove|delete|uninstall/.test(text(dialogs[0])) && text(dialogs[0]).includes(norm(name))) {
      const confirm = clickable(dialogs[0]).filter(e => ['remove', 'delete', 'uninstall', 'confirm', 'yes, remove', 'yes, delete'].includes(text(e)));
      if (confirm.length === 1) return {state: 'click', step: 'confirm', ok: mark(confirm[0])};
      return {state: 'stuck', note: 'The remove confirmation has no single confirm button.'};
    }
    if (dialogs.length) return {state: 'stuck', note: 'Another dialog is open.'};
    const found = rows(name);
    if (!found.length) return {state: 'done'};
    if (found.length > 1) return {state: 'stuck', note: 'More than one ' + name + ' connector is listed; remove the extras yourself.'};
    const row = found[0];
    const direct = clickable(row).filter(e => ['remove', 'delete', 'uninstall'].includes(text(e)));
    if (direct.length === 1) return {state: 'click', step: 'row-remove', ok: mark(direct[0])};
    const menu = clickable(row).filter(e => e.getAttribute('aria-haspopup') === 'menu' ||
      /^(more|options|more options|actions|settings|manage|…|\.\.\.)$/.test(text(e)) ||
      /more|options|actions|menu/.test(norm(e.getAttribute('aria-label'))));
    if (menu.length === 1) return {state: 'click', step: 'open-menu', ok: mark(menu[0])};
    // Some lists open a details page when the name is clicked.
    const open = clickable(row).filter(e => text(e) === norm(name));
    if (open.length === 1) return {state: 'click', step: 'open-details', ok: mark(open[0])};
    return {state: 'stuck', note: 'Found the old connector but no way to remove it.'};
  }

  /* The submit button of the Add custom connector/MCP server dialog. */
  function submitButton(provider) {
    const title = provider === 'ChatGPT' ? 'add custom mcp server' : 'add custom connector';
    const mcpField = d => all(d, 'input,textarea').some(i => /\/mcp\b|server url|mcp server/i.test((i.placeholder || '') + ' ' + (i.getAttribute('aria-label') || '') + ' ' + (i.value || '')));
    const dialogs = all(document, '[role=dialog],[aria-modal=true],dialog').filter(d =>
      all(d, 'h1,h2,h3,[role=heading]').some(h => text(h) === title) || mcpField(d) || /oauth client|authentication/.test(text(d)));
    const inner = dialogs.filter(d => !dialogs.some(o => o !== d && d.contains(o)));
    if (inner.length !== 1) return {state: 'missing'};
    const names = provider === 'ChatGPT' ? ['create', 'create as a plugin', 'add', 'connect', 'save'] : ['add', 'continue', 'connect', 'save'];
    const buttons = clickable(inner[0]).filter(e => names.includes(text(e)));
    if (buttons.length !== 1) return {state: 'missing'};
    return {state: 'click', label: text(buttons[0]), ok: mark(buttons[0])};
  }

  globalThis.__haConnectorManage = Object.freeze({removeStep, submitButton, clear});
})();
