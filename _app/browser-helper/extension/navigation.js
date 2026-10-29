/* Setup-menu navigation only. Never fills, submits, deletes, or approves a connector.
   Invoked by the helper after a toolbar click; no persistent website permission. */
(() => {
  'use strict';
  if (globalThis.__haSetupNavigator?.version === '1.2.0') return;
  const norm = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const visible = el => el && el.isConnected && !el.hidden && getComputedStyle(el).display !== 'none' &&
    getComputedStyle(el).visibility !== 'hidden' && !el.closest('[aria-hidden=true],[inert]') && el.getClientRects().length > 0;
  const all = (root, selector) => [...root.querySelectorAll(selector)].filter(visible);
  const label = el => {
    const referenced = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ').trim();
    return norm(el.getAttribute('aria-label') || referenced || el.innerText || el.textContent || el.getAttribute('title'));
  };
  const controls = root => all(root, 'button,[role=button],[role=menuitem],a[role=menuitem]')
    .filter(el => !el.disabled && el.getAttribute('aria-disabled') !== 'true' &&
      !(el.closest('form') && (el.type === 'submit' || el.getAttribute('type') === 'submit')));
  let clicked = new Set();
  let tries = new Map();
  let attempts = 0;
  let planOnly = false;
  function provider() {
    if (location.protocol !== 'https:') return null;
    if (location.host === 'chatgpt.com' && /^\/plugins\/?$/.test(location.pathname)) return 'ChatGPT';
    if (location.host === 'claude.ai' && location.pathname === '/new' &&
        location.hash === '#customize/connectors') return 'Claude';
    return null;
  }
  function take(elements, key) {
    const unique = [...new Set(elements)];
    if (unique.length > 1) return {state:'blocked', note:'More than one matching setup control is visible. Open the connector form manually, then use Fill.'};
    if (!unique.length) return null;
    const previous = tries.get(key);
    if (previous && Date.now() - previous.at < 1500) return null;
    if (previous?.count >= 2) return {state:'blocked', note:'The connector navigation control did not open the next step. The setup tab is available to finish by hand.'};
    const target = unique[0];
    if (target.getAttribute('aria-expanded') === 'true') return null;
    if (++attempts > 6) return {state:'blocked', note:'Setup has additional steps. Open the custom connector form manually, then use Fill.'};
    clicked.add(key);
    tries.set(key, {count:(previous?.count || 0)+1, at:Date.now()});
    document.querySelectorAll('[data-ha-navigation-target]').forEach(e => e.removeAttribute('data-ha-navigation-target'));
    target.setAttribute('data-ha-navigation-target', '1');
    if (planOnly) return {state:'click', note:'Opening connector setup…', control:key};
    // Submenus may open on hover; a click remains limited to a recognized navigation item.
    if (target.getAttribute('aria-haspopup') === 'menu') {
      target.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
      target.dispatchEvent(new PointerEvent('pointermove', {bubbles:true,pointerType:'mouse'}));
    }
    target.click();
    return {state:'clicked', note:'Opening connector setup…', control:key};
  }
  function step(prepare = false) {
    planOnly = prepare;
    const who = provider();
    if (!who) return {state:'blocked',note:'Navigation is limited to the official connector settings page.'};
    const info = globalThis.__haFormHelper?.probe();
    if (info && ['connection','authentication'].includes(info.kind))
      return {state:'ready',kind:info.kind,provider:who,note:'The '+who+' form is open. Click Fill this page.'};
    // Do not operate underneath any unrelated dialog or registration/login overlay.
    if (all(document, '[role=dialog],[aria-modal=true],dialog').length)
      return {state:'blocked',note:'Another dialog is open. Finish or close it, then click the helper again.'};
    const wanted = who === 'ChatGPT' ? ['add custom mcp server'] : ['add custom connector'];
    let result = take(controls(document).filter(e => wanted.includes(label(e))), 'custom-form');
    if (result) return result;
    const menus = all(document, '[role=menu]');
    if (who === 'Claude' && menus.length) {
      const expandedCustom = menus.flatMap(m => controls(m)).filter(e => label(e) === 'custom' && e.getAttribute('aria-expanded') === 'true');
      if (expandedCustom.length === 1) clicked.add('custom');
      // Only allow Web after this operation has opened the Custom submenu.
      if (clicked.has('custom')) {
        result = take(menus.flatMap(m => controls(m)).filter(e => label(e) === 'web'), 'web');
        if (result) return result;
      }
      result = take(menus.flatMap(m => controls(m)).filter(e => label(e) === 'custom'), 'custom');
      if (result) return result;
    }
    if (who === 'ChatGPT' && menus.length)
      return {state:'pending',note:'The plugin menu is open, but Add custom MCP server is not visible yet.'};
    // Named add controls are acceptable on the specific connector settings route.
    const names = who === 'ChatGPT' ? ['add plugin','add plugins','add new plugin','new plugin','create plugin'] :
      ['add connector','add connectors','add new connector'];
    const named = controls(document).filter(e => names.includes(label(e)));
    result = take(named, 'add-menu');
    if (result) return result;
    // An unlabeled +/Add is allowed only beside an exact Plugins/Connectors heading.
    const headingName = who === 'ChatGPT' ? 'plugins' : 'connectors';
    const matches = [];
    for (const heading of all(document, 'h1,h2,h3,[role=heading]')) {
      if (label(heading) !== headingName) continue;
      let parent = heading.parentElement;
      for (let n=0; parent && parent !== document.body && n<3; n++, parent=parent.parentElement) {
        const items = controls(parent);
        if (items.length > 10 || parent.querySelector('[contenteditable=true],textarea')) break;
        const add = items.filter(e => ['+','＋','add','+ add','add +'].includes(label(e)));
        if (add.length) {matches.push(...add);break;}
      }
    }
    result = take(matches, 'add-menu');
    return result || {state:'pending',note:'Waiting for the connector settings controls. Sign in if required.'};
  }
  globalThis.__haSetupNavigator = {version:'1.2.0',step,plan(){return step(true);},reset(){clicked=new Set();tries=new Map();attempts=0;}};
})();
