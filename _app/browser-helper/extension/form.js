/* Runs in the extension isolated world: invoked form fill, or HA's approval page.
   Never submits a form, clicks final approval, reads chats, or installs a connector. */
(() => {
  'use strict';
  const VERSION = '1.0.0';
  if (globalThis.__haFormHelper?.version === VERSION) return;
  const norm = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const visible = el => !!el && el.isConnected && !el.hidden && getComputedStyle(el).display !== 'none' &&
    getComputedStyle(el).visibility !== 'hidden' && el.getClientRects().length > 0;
  const all = (root, selector) => [...root.querySelectorAll(selector)].filter(visible);
  const text = el => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();
  function provider() {
    if (location.protocol !== 'https:') return null;
    if (['chatgpt.com', 'chat.openai.com'].includes(location.host)) return 'ChatGPT';
    if (location.host === 'claude.ai') return 'Claude';
    return null;
  }
  function label(el, root) {
    const parts = [el.getAttribute('aria-label'), el.getAttribute('placeholder'), el.getAttribute('name')];
    for (const id of (el.getAttribute('aria-labelledby') || '').split(/\s+/)) {
      const target = document.getElementById(id);
      if (target && root.contains(target)) parts.push(text(target));
    }
    for (const l of el.labels || []) if (root.contains(l)) parts.push(text(l));
    // Some React forms use nearby non-for labels. Only inspect the field's immediate group.
    let parent = el.parentElement;
    for (let i = 0; i < 2 && parent && parent !== root; i++, parent = parent.parentElement) {
      const controls = parent.querySelectorAll('input:not([type=hidden]),textarea,select,[role=combobox]');
      if (controls.length > 1) break;
      for (const l of parent.querySelectorAll('label')) parts.push(text(l));
    }
    return norm(parts.filter(Boolean).join(' | '));
  }
  function field(root, kind) {
    const elements = all(root, 'input:not([type=hidden]):not([type=password]):not([type=checkbox]):not([type=radio]):not([type=file]),textarea')
      .filter(e => !e.disabled && !e.readOnly);
    const patterns = {
      name: /(^|[|\s])(name|connector name|custom tool)([|\s]|$)/,
      endpoint: /mcp server url|server url|server_url|https:\/\/[^|\s]+\/mcp|\bendpoint\b/,
      description: /description|explain what it does/
    };
    const found = elements.filter(e => patterns[kind].test(label(e, root)));
    if (found.length > 1) throw new Error('More than one ' + kind + ' field was found. Nothing was submitted.');
    return found[0] || null;
  }
  function titleMatches(root, who) {
    const titles = all(root, 'h1,h2,h3,[role=heading]');
    const expected = who === 'ChatGPT' ? /^add custom mcp server$/i : /^add custom connector$/i;
    return titles.some(h => expected.test(text(h)));
  }
  function connectionRoot(who, allowAuth = false) {
    let roots = all(document, '[role=dialog],[aria-modal=true],dialog');
    roots = [...new Set(roots)];
    let matched = roots.filter(r => titleMatches(r, who));
    // Prefer the innermost matching dialog, not a surrounding modal host.
    matched = matched.filter(r => !matched.some(other => other !== r && r.contains(other)));
    if (matched.length > 1) throw new Error('Multiple connector dialogs are open. Close the others first.');
    if (matched.length === 1) return matched[0];
    // Fallback only around an exact connector heading, never around chat content/body.
    for (const heading of all(document, 'h1,h2,h3,[role=heading]')) {
      const wanted = who === 'ChatGPT' ? 'add custom mcp server' : 'add custom connector';
      if (norm(text(heading)) !== wanted) continue;
      let p = heading.parentElement;
      for (let i = 0; p && p !== document.body && i < 5; i++, p = p.parentElement) {
        if (p.querySelector('[contenteditable=true],textarea[placeholder*="Message"]')) break;
        if (field(p, 'endpoint') && field(p, 'name')) return p;
      }
    }
    if (allowAuth && who === 'Claude') {
      const auth = roots.filter(r => /authentication/i.test(text(r)) && /oauth client/i.test(text(r)) &&
        all(r, 'button,input[type=submit]').some(b => /^(continue|add)$/i.test(text(b) || b.value || '')));
      if (auth.length === 1) return auth[0];
    }
    return null;
  }
  function pairForm() {
    if (location.protocol !== 'https:' || location.pathname !== '/authorize') return null;
    const headings = all(document, 'h1');
    if (!headings.some(h => /^connect hivemind assembly$/i.test(text(h)))) return null;
    const candidates = all(document, 'form').filter(f => {
      try { return f.method.toLowerCase() === 'post' && new URL(f.action, location.href).origin === location.origin &&
        new URL(f.action, location.href).pathname === '/authorize' &&
        f.querySelector('input[name=pairing_code]') && f.querySelector('input[name=flow][type=hidden]'); }
      catch { return false; }
    });
    return candidates.length === 1 ? candidates[0] : null;
  }
  function callbackProvider() {
    try {
      const u = new URL(new URL(location.href).searchParams.get('redirect_uri'));
      if (u.protocol !== 'https:') return null;
      if (['chatgpt.com', 'chat.openai.com'].includes(u.host)) return 'ChatGPT';
      if (['claude.ai', 'claude.com'].includes(u.host)) return 'Claude';
    } catch { /* no provider */ }
    return null;
  }
  function probe() {
    const who = provider();
    if (who) {
      const root = connectionRoot(who, true);
      return {kind: root ? (field(root, 'endpoint') ? 'connection' : 'authentication') : 'provider', provider: who,
        page_url: location.href, note: root ? '' : 'Open the Add custom ' + (who === 'ChatGPT' ? 'MCP server' : 'connector') + ' dialog first.'};
    }
    const f = pairForm();
    if (f) return {kind: 'pairing', provider: callbackProvider(), page_url: location.href,
      flow: f.querySelector('input[name=flow]').value};
    return {kind: 'unsupported', note: 'Use this helper only on a ChatGPT/Claude connector form or the current HA approval page.'};
  }
  function setValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (!setter) throw new Error('This field does not support safe autofill.');
    setter.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
    el.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
    el.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
  }
  function exactClickables(root, expressions) {
    const candidates = all(root, 'button,[role=button],[role=tab],[role=radio],[role=option],label,input[type=radio]');
    return candidates.filter(el => expressions.includes(norm(text(el) || el.getAttribute('aria-label') || el.value)));
  }
  function controlByLabel(root, wanted) {
    return all(root, 'select,[role=combobox]').filter(e => label(e, root).includes(wanted));
  }
  async function choose(root, labelText, values) {
    const wanted = values.map(norm);
    const controls = controlByLabel(root, labelText);
    let element = controls.length === 1 ? controls[0] : null;
    if (!element) {
      // A Radix-style trigger often wraps the selected value under a nearby plain label.
      for (const l of all(root, 'label')) if (norm(text(l)).replace(/:$/, '') === labelText) {
        const target = l.htmlFor ? document.getElementById(l.htmlFor) : null;
        const container = l.parentElement;
        const near = target ? [target] : all(container, 'select,[role=combobox],button[aria-haspopup=listbox]');
        if (near.length === 1 && root.contains(near[0])) { element = near[0]; break; }
      }
    }
    if (element && element.tagName === 'SELECT') {
      const option = [...element.options].find(o => wanted.includes(norm(o.textContent)));
      if (!option) return false;
      if (element.value !== option.value) {
        Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(element, option.value);
        element.dispatchEvent(new Event('input', {bubbles:true}));
        element.dispatchEvent(new Event('change', {bubbles:true}));
      }
      return element.value === option.value;
    }
    if (element) {
      if (wanted.includes(norm(text(element)))) return true;
      if (element.disabled || element.getAttribute('aria-disabled') === 'true') return false;
      const before = new Set(all(document, '[role=listbox],[role=menu]'));
      element.click(); await pause(100);
      const controlled = element.getAttribute('aria-controls');
      const list = controlled ? document.getElementById(controlled) : null;
      const lists = list && visible(list) ? [list] : all(document, '[role=listbox],[role=menu]').filter(x => !before.has(x));
      if (lists.length !== 1) return false;
      const options = all(lists[0], '[role=option],[role=menuitem],[role=menuitemradio]')
        .filter(o => wanted.includes(norm(text(o))));
      if (options.length !== 1) return false;
      options[0].click(); await pause(100);
      // A controlled UI may replace its trigger; verify the current labelled control.
      const current = controlByLabel(root, labelText);
      return wanted.includes(norm(text(current.length === 1 ? current[0] : element)));
    }
    // Explicit radio controls, scoped to a labelled fieldset/group.
    const group = all(root, 'fieldset,[role=radiogroup]').find(g => norm(text(g.querySelector('legend')) || g.getAttribute('aria-label')).includes(labelText));
    if (group) {
      const matches = all(group, 'label,[role=radio]').filter(e => wanted.includes(norm(text(e))));
      if (matches.length === 1) { matches[0].click(); await pause(50); return true; }
    }
    return false;
  }
  function riskCheckbox(root) {
    // React/Radix can expose one checkbox as a role=checkbox control AND a
    // native input used for form submission. Count logical controls, not nodes.
    const raw = all(root, 'input[type=checkbox],[role=checkbox]');
    const hiddenProxy = el => el.tagName === 'INPUT' && (el.getAttribute('aria-hidden') === 'true' ||
      getComputedStyle(el).opacity === '0' || getComputedStyle(el).pointerEvents === 'none');
    const canonical = el => {
      const ancestor = el.parentElement?.closest('[role=checkbox]');
      if (ancestor && root.contains(ancestor) && visible(ancestor)) return ancestor;
      if (hiddenProxy(el)) {
        const siblings = [...el.parentElement.querySelectorAll('[role=checkbox]')].filter(visible);
        if (siblings.length === 1) return siblings[0];
      }
      return el;
    };
    const controls = [...new Set(raw.map(canonical))];
    const candidates = controls.filter(el => {
      if (label(el, root).includes('i understand and want to continue')) return true;
      let parent = el.parentElement;
      for (let i=0; i<3 && parent && parent!==root; i++,parent=parent.parentElement) {
        const inGroup = controls.filter(c=>parent.contains(c));
        if (inGroup.length !== 1) break;
        if (/i understand and want to continue/i.test(text(parent))) return true;
      }
      return false;
    });
    if (candidates.length > 1) throw new Error('Multiple consent controls are visible. Tick the acknowledgment yourself.');
    return candidates[0] || null;
  }
  async function fill(data, replace = false) {
    const who = provider();
    if (!who || who !== data.provider) throw new Error('This tab does not match the selected assistant.');
    if (typeof data.endpoint !== 'string' || !/^https:\/\/[^/]+\/mcp$/.test(data.endpoint)) throw new Error('HA did not provide a valid address.');
    const root = connectionRoot(who, true);
    if (!root) throw new Error('Open the provider’s Add custom connector/server dialog, then click Fill this page again.');
    const name = field(root, 'name'), endpoint = field(root, 'endpoint'), description = field(root, 'description');
    const filled = [], warnings = [];
    if (name || endpoint) {
      if (!name || !endpoint) throw new Error('The name and server-address fields could not both be identified. Nothing was changed.');
      const edits = [[name, data.name, 'Name'], [endpoint, data.endpoint, who === 'ChatGPT' ? 'Server URL' : 'MCP server URL']];
      if (description) edits.push([description, data.description, 'Description']);
      for (const [el, value, title] of edits) {
        if (el.value.trim() && el.value.trim() !== value && !replace)
          throw new Error(title + ' already contains a different value. Review it, then enable Replace existing form values to update it.');
      }
      if (who === 'ChatGPT') {
        const tabs = exactClickables(root, ['server url']);
        if (tabs.length === 1 && !tabs[0].disabled) tabs[0].click();
      }
      for (const [original, value, title] of edits) {
        const kind = title === 'Name' ? 'name' : title === 'Description' ? 'description' : 'endpoint';
        const el = original.isConnected ? original : field(root, kind);
        if (!el) throw new Error('The form changed before it could be filled. Try again.');
        setValue(el, value); filled.push(title);
      }
      await pause(120);
      for (const [, value, title] of edits) {
        const kind = title === 'Name' ? 'name' : title === 'Description' ? 'description' : 'endpoint';
        const currentRoot = connectionRoot(who, true);
        if (!currentRoot || field(currentRoot, kind)?.value !== value)
          throw new Error('The page did not retain ' + title + '. Nothing was submitted; retry or paste the value manually.');
      }
    }
    const current = connectionRoot(who, true) || root;
    if (who === 'ChatGPT') {
      if (await choose(current, 'authentication', ['OAuth'])) filled.push('OAuth');
      else warnings.push('Confirm Authentication is OAuth. Leave Advanced OAuth settings on discovery unless the site requests a choice.');
      // User explicitly authorized this one risk acknowledgment. No other consent is checked.
      const checkbox = riskCheckbox(connectionRoot(who, true) || current);
      if (data.acknowledge_risk === true && checkbox) {
        if (!(checkbox.checked === true || checkbox.getAttribute('aria-checked') === 'true')) checkbox.click();
        await pause(80);
        const fresh = riskCheckbox(connectionRoot(who, true) || current);
        if (fresh?.checked === true || fresh?.getAttribute('aria-checked') === 'true') filled.push('I understand and want to continue');
        else warnings.push('The acknowledgment did not stay selected; check it manually.');
      } else warnings.push('The risk acknowledgment was not found; review it on the page.');
    } else if (!endpoint || /oauth client/i.test(text(current))) {
      if (await choose(current, 'authentication', ['Sign in now'])) filled.push('Sign in now');
      else warnings.push('Select Sign in now if the Authentication choice is shown.');
      if (await choose(current, 'oauth client', ['Register automatically'])) filled.push('Register automatically');
      else warnings.push('Select Register automatically under OAuth client. Do not enter a client secret.');
    }
    return {filled, warnings, submitted:false, next:who === 'ChatGPT' ?
      'Click Create, then approve it on HA’s page.' :
      endpoint ? 'Click Continue. Fill again if authentication options appear.' :
      'Click Continue or Add, then approve it on HA’s page.'};
  }
  async function fillPair(data) {
    const form = pairForm();
    if (!form || location.origin !== data.origin || form.querySelector('[name=flow]').value !== data.flow ||
      callbackProvider() !== data.provider) throw new Error('This is not the approval request HA checked.');
    if (!/^[A-Za-z0-9_-]{10,64}$/.test(data.pairing_code || '')) throw new Error('HA did not supply a valid approval code.');
    const input = form.querySelector('input[name=pairing_code]');
    setValue(input, data.pairing_code); await pause(50);
    if (input.value !== data.pairing_code) throw new Error('The page did not retain the pairing code.');
    const hint=document.getElementById('ha-pair-status');
    if(hint) hint.textContent='Code filled by the HA helper. Click Approve.';
    return {filled:['One-time pairing code'], warnings:[], submitted:false,
      next:'Code filled. Click Approve.'};
  }
  globalThis.__haFormHelper = Object.freeze({version:VERSION, probe, fill, fillPair});
})();
