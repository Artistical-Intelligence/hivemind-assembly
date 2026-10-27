// AI assistants page: one sign-in button per service, saved setups, and one compact row
// per assistant whose Model and Thinking lists come from each service's own model picker.
(() => {
  const el = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const PROVIDER = {openai: 'ChatGPT', claude: 'Claude'};
  const MODE = {Chat: 'Chat', Work: 'Work', native: ''};
  const ORDER = ['adviser.extra', 'reviewer.high', 'worker.opus', 'worker.astra', 'worker.extra'];
  const SLOT = {'adviser.extra': 'Adviser', 'reviewer.high': 'Reviewer', 'worker.opus': 'Worker 1', 'worker.astra': 'Worker 2', 'worker.extra': 'Worker 3'};
  const FIELDS = ['provider', 'mode', 'model', 'effort'];
  const STEPS = ['Open a tab', 'Sign in', 'Find the model and effort', 'Read usage', 'Test the conversation'];
  const CONTROL = {mode: 'mode picker', model: 'model picker', effort: 'effort picker', account: 'account name',
    composer: 'message box', send: 'send button', attachments: 'attach button'};

  const minutes = since => since ? Math.max(0, Math.round((Date.now() / 1000 - since) / 60)) : 0;
  const forHow = since => {
    const m = minutes(since);
    return m < 1 ? '' : m === 1 ? ' (for 1 min)' : ` (for ${m} min)`;
  };

  // What the assistant is doing, in plain words, and whether the owner needs to act.
  function describe(r) {
    const s = r.setup || {};
    const name = PROVIDER[r.provider] || r.provider;
    const stuck = minutes(s.since) >= 2;
    if (r.status.ready) return {text: 'Ready.', tone: 'ok', step: 5};
    if (r.out_of_usage) return {text: 'Out of usage on this account. HA checks again once a day and continues when it refills.', tone: 'warn', step: 3};
    switch (s.stage) {
      case 'opening':
        return {text: `Opening ${name} in a tab…`, step: 0};
      case 'authentication':
        return {
          text: /already open/.test(s.instruction || '')
            ? `Waiting for you to sign in to ${name} (one sign-in covers all its assistants).`
            : `Sign in to ${name} with its button above. Setup continues by itself.`,
          tone: 'act', step: 1};
      case 'binding_required': {
        const missing = (s.instruction || '').split(':').pop().split(',').map(x => CONTROL[x.trim()] || x.trim()).filter(Boolean);
        // The page said exactly what's wrong (for example, a model this account doesn't offer).
        if (s.detail) return {text: s.detail + ' HA tries again every 30 seconds.', tone: stuck ? 'warn' : '', step: 2};
        return {
          text: stuck
            ? `HA can't find the ${missing.join(', ')} on the ${name} page. See What HA sees; a pop-up or a changed page may be in the way.`
            : `Looking for the ${missing.join(', ') || 'controls'} on the ${name} page…`,
          tone: stuck ? 'warn' : '', step: 2};
      }
      case 'allowance_mapping':
        return {text: stuck ? `HA can't find ${name}'s usage page for this account.` : `Reading ${name} usage…`, tone: stuck ? 'warn' : '', step: 3};
      case 'waiting_quota':
        return {text: 'Waiting for this account to have enough usage left (at least 10%).', tone: 'warn', step: 3};
      case 'waiting_delivery':
        return {text: s.instruction || 'Retrying…', tone: 'act', step: 4};
      case 'ready_for_session':
      case 'bound':
        return {text: 'Found the controls. Starting its own conversation…', step: 4};
      case 'verified':
        return {text: 'Set up. Checking it is ready…', step: 5};
      case 'attention':
        return {text: s.instruction || 'Setup stopped.', tone: 'warn', step: null};
      case 'not_started':
        return {text: s.instruction || 'Not set up yet.', step: null};
      default:
        return {text: 'Not set up yet.', step: null};
    }
  }

  // The dropdowns edit a draft; Use puts it on the assistants, Save keeps it as a setup.
  let last = null, draft = null, dirty = false, chosen = null, painted = '';
  const pick = t => Object.fromEntries(FIELDS.map(f => [f, t[f] ?? '']));
  const inUse = s => Object.fromEntries(s.routes.map(r => [r.id, pick(r)]));
  const same = (a, b) => !!a && !!b && ORDER.every(r => a[r] && b[r] && FIELDS.every(f => (a[r][f] || '') === (b[r][f] || '')));
  const clone = v => JSON.parse(JSON.stringify(v));

  // {provider: {mode: {model: [thinking levels]}}}: what each picker offered, plus anything in use or saved.
  function catalog(s) {
    const out = {};
    const add = (p, m, model, levels) => {
      if (!p || !model) return;
      const list = (((out[p] ||= {})[m] ||= {})[model] ||= []);
      for (const level of levels || []) if (level && !list.includes(level)) list.push(level);
    };
    for (const [p, found] of Object.entries(s.model_choices || {})) {
      for (const [m, models] of Object.entries(found?.modes || {})) for (const [model, levels] of Object.entries(models)) add(p, m, model, levels);
    }
    const presets = Object.values(s.assistant_setups?.presets || {}).flatMap(Object.values);
    for (const t of [...Object.values(inUse(s)), ...presets, ...Object.values(draft || {})]) add(t.provider, t.mode, t.model, t.effort ? [t.effort] : []);
    return out;
  }
  const levelsOf = (cat, t) => cat[t.provider]?.[t.mode]?.[t.model] || [];

  function modelSelect(route, t, cat) {
    const value = JSON.stringify([t.provider, t.mode, t.model]);
    const groups = Object.entries(cat).flatMap(([p, modes]) => Object.entries(modes).map(([m, models]) =>
      `<optgroup label="${esc((PROVIDER[p] || p) + (MODE[m] ? ' ' + MODE[m] : ''))}">` + Object.keys(models).map(model => {
        const v = JSON.stringify([p, m, model]);
        // ChatGPT has Chat and Work: name it, so the closed list still says which.
        return `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(model + (MODE[m] ? ' (' + MODE[m] + ')' : ''))}</option>`;
      }).join('') + '</optgroup>'));
    return `<select data-role-model="${esc(route)}" aria-label="${esc(SLOT[route])} model">${groups.join('')}</select>`;
  }

  function levelSelect(route, t, cat) {
    const levels = levelsOf(cat, t);
    const options = levels.length ? levels.map(l => `<option${l === t.effort ? ' selected' : ''}>${esc(l)}</option>`).join('') : '<option value="">None</option>';
    return `<select data-role-effort="${esc(route)}" aria-label="${esc(SLOT[route])} thinking"${levels.length ? '' : ' disabled'}>${options}</select>`;
  }

  function row(r, cat) {
    const s = r.setup || {};
    const d = describe(r);
    const working = s.running || ['opening', 'authentication', 'binding_required', 'allowance_mapping', 'waiting_delivery', 'ready_for_session', 'bound'].includes(s.stage);
    const step = d.step !== null && !r.status.ready ? `<span class="muted"> Step ${Math.min(d.step + 1, STEPS.length)} of ${STEPS.length}${esc(forHow(s.since))}</span>` : '';
    const actions = [
      s.tab_open ? `<button data-native-show="${esc(r.id)}">Show tab</button>` : `<button data-native-setup="${esc(r.id)}"${working ? ' disabled' : ''}>${r.status.ready ? 'Set up again' : 'Set up'}</button>`,
      s.snapshot ? `<button data-native-snapshot="${esc(r.id)}">What HA sees</button>` : '',
      `<details class="row-more"><summary>More</summary><div class="row-menu"><button data-probe="${esc(r.id)}">Check it works</button><button data-native-renew="${esc(r.id)}">New conversation</button></div></details>`,
    ].join('');
    return `<tr data-route="${esc(r.id)}"><th scope="row">${esc(SLOT[r.id] || r.id)}</th>`
      + `<td>${modelSelect(r.id, draft[r.id], cat)}</td><td>${levelSelect(r.id, draft[r.id], cat)}</td>`
      + `<td><span class="status ${d.tone || ''}">${esc(d.text)}</span>${step}</td><td class="row-actions">${actions}</td></tr>`;
  }

  function paint() {
    const s = last;
    if (!s?.routes) return;
    const live = inUse(s);
    if (!draft || !dirty) draft = clone(live);
    const presets = s.assistant_setups?.presets || {};
    const active = s.assistant_setups?.active || null;
    if (chosen === null || !(chosen in presets)) chosen = active && active in presets ? active : Object.keys(presets)[0] || '';
    const cat = catalog(s);
    const routes = ORDER.map(id => s.routes.find(r => r.id === id)).filter(Boolean);
    // Don't rebuild the table while a list is open or anything in it has focus.
    const table = el('role-rows');
    const busy = table.contains(document.activeElement) && document.activeElement.tagName === 'SELECT';
    const sig = JSON.stringify([draft, cat, routes.map(r => [describe(r), r.setup, r.status.ready])]);
    if (!busy && sig !== painted) {
      const open = new Set([...table.querySelectorAll('details.row-more[open]')].map(x => x.closest('tr').dataset.route));
      table.innerHTML = routes.map(r => row(r, cat)).join('');
      table.querySelectorAll('details.row-more').forEach(x => { if (open.has(x.closest('tr').dataset.route)) x.open = true; });
      painted = sig;
    }
    const names = Object.keys(presets);
    const select = el('setup-name');
    if (select.dataset.names !== JSON.stringify(names)) {
      select.innerHTML = names.map(n => `<option>${esc(n)}</option>`).join('');
      select.dataset.names = JSON.stringify(names);
    }
    select.value = chosen;
    const live_ = same(draft, live);
    el('setup-state').textContent = live_
      ? (active ? `In use: ${active}.` : 'In use (not saved as a setup).')
      : 'Changed here, not in use yet: select Use to switch the assistants.';
    el('setup-use').classList.toggle('primary', !live_);
    // Services: one button each, showing who is signed in.
    el('service-buttons').innerHTML = (s.services || []).map(v =>
      `<button type="button" class="service${v.account ? ' signed' : ''}" data-signin="${esc(v.provider)}"><b>${esc(v.name)}</b><span>${v.account ? esc(v.account) : v.waiting ? 'Sign in now' : 'Open to sign in'}</span></button>`).join('');
    const choices = s.model_choices || {};
    const errors = Object.entries(choices).filter(([k, v]) => k !== 'read_at' && v?.error).map(([, v]) => v.error);
    el('choices-state').textContent = (choices.read_at
      ? `Model choices read from ChatGPT and Claude at ${new Date(choices.read_at * 1000).toLocaleString()}.`
      : 'The lists show only models already in use until HA reads ChatGPT\'s and Claude\'s model menus.') + (errors.length ? ' ' + errors.join(' ') : '');
    el('choices-read').textContent = choices.read_at ? 'Read again' : 'Read choices';
    const ready = s.routes.filter(r => r.status.ready).length;
    const working = s.routes.some(r => r.setup?.running);
    el('assistants-overall').hidden = false;
    el('assistants-overall-bar').max = s.routes.length;
    el('assistants-overall-bar').value = ready;
    el('assistants-overall-text').textContent = `${ready} of ${s.routes.length} assistants ready` + (working ? '. Setting up the others…' : '.');
    el('native-all').textContent = ready === s.routes.length ? 'Set up all again' : 'Set up all';
    const mode = s.assistant_browser?.mode;
    el('browser-mode-now').textContent = mode === 'your_chrome' ? 'your Chrome' : 'HA\'s own Chrome windows';
  }

  function render(s) {
    last = s;
    paint();
  }

  document.addEventListener('change', e => {
    const model = e.target.closest('[data-role-model]');
    const level = e.target.closest('[data-role-effort]');
    if (e.target.id === 'setup-name') {
      // Picking a setup loads it into the lists; Use switches the assistants to it.
      chosen = e.target.value;
      const preset = last?.assistant_setups?.presets?.[chosen];
      if (preset) { draft = clone(preset); dirty = !same(draft, inUse(last)); }
      paint();
      return;
    }
    if (!model && !level) return;
    const route = model ? model.dataset.roleModel : level.dataset.roleEffort;
    if (model) {
      const [provider, mode, name] = JSON.parse(model.value);
      const levels = levelsOf(catalog(last), {provider, mode, model: name});
      const before = draft[route].effort;
      // Keep the thinking level when the new model offers it; otherwise a middle one.
      draft[route] = {provider, mode, model: name, effort: levels.includes(before) ? before : (levels[Math.floor((levels.length - 1) / 2)] || '')};
    } else {
      draft[route].effort = level.value;
    }
    dirty = !same(draft, inUse(last));
    painted = '';
    document.activeElement?.blur?.();
    paint();
  });

  document.addEventListener('click', async e => {
    // A More menu closes when something in it is chosen or the click lands elsewhere.
    for (const menu of document.querySelectorAll('details.row-more[open]')) {
      if (!menu.contains(e.target) || e.target.closest('.row-menu button')) menu.open = false;
    }
    const show = e.target.closest('[data-native-show]');
    const picture = e.target.closest('[data-native-snapshot]');
    const signin = e.target.closest('[data-signin]');
    const id = e.target.closest('button')?.id;
    try {
      if (show) {
        const r = await api('native/show', {route: show.dataset.nativeShow});
        notice(r.shown ? 'Switched to that tab in Chrome.' : 'That tab is closed. Select Set up to open it again.', !r.shown);
      }
      if (picture) {
        const r = await api('native/snapshot', {route: picture.dataset.nativeSnapshot});
        const view = el('snapshot-view');
        view.querySelector('img').src = 'data:image/jpeg;base64,' + r.jpeg;
        view.querySelector('p').textContent = 'What HA saw in this tab' + (r.taken ? ' at ' + new Date(r.taken * 1000).toLocaleTimeString() : '') + '.';
        view.showModal();
      }
      if (signin) {
        await api('native/signin', {provider: signin.dataset.signin});
        notice('Opened ' + (PROVIDER[signin.dataset.signin] || signin.dataset.signin) + ' in Chrome. Sign in there if it asks.');
      }
      if (id === 'setup-use') {
        const preset = last?.assistant_setups?.presets?.[chosen];
        const r = await api('assistants/use', same(draft, preset) ? {name: chosen} : {targets: draft});
        dirty = false;
        notice(r.changed.length ? `Using it. Setting up ${r.changed.map(x => SLOT[x] || x).join(', ')} again.` : 'Already in use.');
        refresh();
      }
      if (id === 'setup-save' || id === 'setup-save-as') {
        const name = id === 'setup-save' ? chosen : el('setup-new-name').value.trim();
        if (!name) throw new Error('Type a name for the new setup first.');
        await api('assistants/save', {name, targets: draft});
        chosen = name;
        el('setup-new-name').value = '';
        notice(`Saved as "${name}".` + (same(draft, inUse(last)) ? '' : ' Select Use to switch the assistants to it.'));
        refresh();
      }
      if (id === 'choices-read') {
        await api('models/read', {});
        notice('Reading ChatGPT\'s and Claude\'s model menus in HA\'s tabs. This takes about a minute; your choices there are put back.');
      }
    } catch (x) {
      notice(x.message, true);
    }
  });
  window.renderAssistants = render;
})();
