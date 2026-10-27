'use strict';
// Reference material: add one document, a whole folder or a whole GitHub repository,
// and see what was imported, what was skipped and why.
(() => {
  const form = document.querySelector('#source-form');
  const collections = document.querySelector('#collection-list');
  const sources = document.querySelector('#source-list');
  if (!form || !collections || !sources) return;
  const field = name => form.elements[name];
  const EVERY = {0: 'Only when I select Update', 1440: 'Every day', 10080: 'Every week'};
  function showWhat() {
    const what = field('what').value;
    for (const el of document.querySelectorAll('[data-what]')) el.hidden = !el.dataset.what.split(' ').includes(what);
    const button = form.querySelector('button.primary');
    button.textContent = what === 'document' ? 'Add document' : what === 'folder' ? 'Import folder' : 'Import repository';
    button.title = what === 'document' ? "Add this document to HA's reference material."
      : what === 'folder' ? 'Import every document in this folder; files HA skips are listed with the reason.'
      : 'Import every document in this repository; files HA skips are listed with the reason.';
    if (what === 'github') loadRepositories();
  }
  let reposLoaded = false;
  async function loadRepositories() {
    if (reposLoaded) return;
    reposLoaded = true;
    try {
      const repos = await api('github/repositories', {});
      document.querySelector('#knowledge-repos').innerHTML = repos.map(r =>
        `<option value="${esc(r.owner + '/' + r.name)}">${r.private ? 'Private' : 'Public'}${r.description ? ': ' + esc(r.description) : ''}</option>`).join('');
    } catch {
      reposLoaded = false;  // Not connected yet: typing owner/name still works.
    }
  }
  field('what').addEventListener('change', showWhat);
  showWhat();
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const button = form.querySelector('button.primary');
    button.disabled = true;
    try {
      const f = new FormData(form);
      const what = f.get('what');
      const tags = f.get('tags')?.trim() ? f.get('tags').split(',').map(x => x.trim()).filter(Boolean) : undefined;
      if (what === 'document') {
        if (!f.get('path')) throw new Error('Choose the document first (Browse…).');
        const r = await api('source', {path: f.get('path'), external_allowed: f.has('external_allowed'), tags});
        notice(r.replaced ? 'Replaced the earlier copy of this document.' : r.unchanged ? 'Already imported; nothing changed.'
          : `Added: ${r.sections} sections.` + (r.older_copy ? ' A document with the same name, added by an earlier version of HA, is still listed; remove it if it was an older copy of this one.' : ''));
      } else {
        const request = {kind: what, external_allowed: f.has('external_allowed'), tags: tags || [],
          schedule_minutes: Number(f.get('schedule_minutes'))};
        if (what === 'folder') {
          if (!f.get('folder')) throw new Error('Choose the folder first (Browse…).');
          request.folder = f.get('folder');
        } else {
          if (!f.get('repository')) throw new Error('Type the repository as owner/name.');
          request.repository = f.get('repository');
          if (f.get('branch')) request.branch = f.get('branch');
        }
        await api('knowledge/import', request);
        notice('Importing. Progress shows under Your reference material.');
      }
      form.reset();
      showWhat();
      refresh();
    } catch (x) {
      notice(x.message, true);
    } finally {
      button.disabled = false;
    }
  });

  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  function counts(c) {
    if (!c) return '';
    const parts = [plural(c.sections || 0, 'section')];
    if (c.tables) parts.push(plural(c.tables, 'table'));
    if (c.pictures) parts.push(plural(c.pictures, 'picture') + (c.pictures_not_described ? ` (${c.pictures_not_described} not yet described)` : ''));
    if (c.links) parts.push(plural(c.links, 'link'));
    return parts.join(', ');
  }
  // The adviser's picture descriptions: one job per document.
  let jobs = [];
  const STAGE = {queued: 'waiting to start', waiting_quota: 'waiting for the adviser (set up, with usage left)',
    running: 'describing', completed: 'done', attention: 'stopped'};
  function jobText(list) {
    return list.map(j => `Picture descriptions: ${STAGE[j.stage] || j.stage}${j.of ? ` (${j.described || 0} of ${j.of})` : ''}${j.reason ? ': ' + j.reason : ''}`).join(' ');
  }
  function describeButton(n, attribute, id) {
    return n ? ` <button type="button" ${attribute}="${esc(id)}">Let the adviser describe ${plural(n, 'picture')}</button>` : '';
  }
  function sourceRow(v) {
    const c = v.counts ? JSON.parse(v.counts) : null;
    const gaps = v.gaps ? JSON.parse(v.gaps) : [];
    const mine = jobs.filter(j => j.source === v.id && j.stage !== 'completed');
    const waiting = v.external_allowed && c && !mine.length ? c.pictures_not_described || 0 : 0;
    return `<li>${esc(v.name)} ${badge(v.external_allowed ? 'assistants may read' : 'private')}<span class="muted"> ${esc(counts(c))}</span>${describeButton(waiting, 'data-describe-source', v.id)}${gaps.length
      ? `<br><span class="warn-text">${esc(gaps.join(' '))}</span>` : ''}${mine.length ? `<br><span class="muted">${esc(jobText(mine))}</span>` : ''}</li>`;
  }
  function where(c) {
    return c.kind === 'github'
      ? `<a href="https://github.com/${encodeURIComponent(c.owner)}/${encodeURIComponent(c.repository)}" target="_blank" rel="noopener noreferrer">${esc(c.owner + '/' + c.repository)}</a>${c.branch ? ' (' + esc(c.branch) + ')' : ''}`
      : esc(c.folder);
  }
  function card(c) {
    const r = c.report;
    const every = Object.entries(EVERY).map(([v, label]) => `<option value="${v}"${Number(v) === c.schedule_minutes ? ' selected' : ''}>${label}</option>`).join('');
    const skipped = r && r.skipped_count ? `<details class="kc-skipped"><summary>Skipped (${r.skipped_count})</summary><p class="muted">${Object.entries(r.skipped_reasons)
      .map(([why, n]) => `${esc(why)}: ${n}`).join(' · ')}</p><ul class="plain">${r.skipped_sample.map(x => `<li>${esc(x.path)}: ${esc(x.reason)}</li>`).join('')}</ul>${r.skipped_count > r.skipped_sample.length
      ? `<button type="button" data-collection-report="${esc(c.id)}">Show all ${r.skipped_count}</button>` : ''}</details>` : '';
    const failed = r && r.failed.length ? `<details open><summary>Couldn't be read (${r.failed.length})</summary><ul class="plain">${r.failed.map(x => `<li>${esc(x.path)}: ${esc(x.reason)}</li>`).join('')}</ul></details>` : '';
    const busy = jobs.filter(j => (c.sources || []).includes(j.source) && j.stage !== 'completed');
    const describe = r && c.external_allowed && !busy.length ? describeButton(r.pictures_not_described || 0, 'data-describe-collection', c.id) : '';
    const what = r ? `<p>${plural(r.documents, 'document')}: ${plural(r.sections, 'section')}, ${plural(r.tables, 'table')}, ${plural(r.pictures, 'picture')}${r.pictures_not_described ? ` (${r.pictures_not_described} not yet described)` : ''}.${r.commit ? ` GitHub version ${esc(r.commit.slice(0, 7))}.` : ''}${describe}</p>${busy.length ? `<p class="muted">${esc(jobText(busy).split(' Picture descriptions: ')[0])}${busy.length > 1 ? ` (${busy.length} documents)` : ''}</p>` : ''}` : '';
    return `<details open data-collection="${esc(c.id)}"><summary>${esc(c.name)} ${badge(c.running ? 'importing' : c.state)}</summary>
      <p class="muted">${where(c)}</p>
      <progress max="100" class="kc-bar"${c.running ? '' : ' hidden'}></progress>
      <p class="kc-message"></p>
      ${what}${failed}${skipped}
      <label>Update it<select data-collection-setting="schedule_minutes">${every}</select></label>
      <label class="check"><input type="checkbox" data-collection-setting="external_allowed"${c.external_allowed ? ' checked' : ''}>Let the assistants read it</label>
      <div class="actions"><button type="button" data-collection-update="${esc(c.id)}"${c.running ? ' disabled' : ''}>${c.kind === 'github' ? 'Update from GitHub' : 'Import again'}</button><button type="button" data-collection-remove="${esc(c.id)}"${c.running ? ' disabled' : ''}>Remove from HA</button></div>
    </details>`;
  }
  window.renderReference = s => {
    jobs = s.picture_descriptions || [];
    const byCollection = {};
    for (const v of s.sources || []) if (v.collection) (byCollection[v.collection] ||= []).push(v.id);
    const items = (s.knowledge_collections || []).map(c => ({...c, sources: byCollection[c.id] || []}));
    const sig = JSON.stringify([items.map(c => [c.id, c.state, c.running, c.schedule_minutes, c.external_allowed, c.report && c.report.finished]),
      jobs.map(j => [j.id, j.stage, j.described])]);
    if (collections.dataset.sig !== sig) {
      collections.dataset.sig = sig;
      collections.innerHTML = items.map(card).join('');
    }
    for (const c of items) {
      const el = collections.querySelector(`[data-collection="${CSS.escape(c.id)}"]`);
      if (!el) continue;
      const bar = el.querySelector('.kc-bar');
      if (c.progress) {
        bar.hidden = false;
        bar.value = c.progress.percent;
      } else bar.hidden = !c.running;
      const when = c.last_import ? ` Last import: ${new Date(c.last_import * 1000).toLocaleString()}.` : '';
      el.querySelector('.kc-message').textContent = (c.progress ? c.progress.text : c.message || '') + (c.running ? '' : when);
    }
    // Single documents; files from folders and repositories are counted above.
    const own = (s.sources || []).filter(v => !v.collection);
    const listed = own.map(sourceRow).join('');
    const html = listed ? `<ul class="plain">${listed}</ul>` : items.length ? '' : '<p class="empty">Nothing added yet.</p>';
    if (sources.dataset.html !== html) {
      sources.dataset.html = html;
      sources.innerHTML = html;
    }
  };
  collections.addEventListener('click', async e => {
    const update = e.target.closest('[data-collection-update]');
    const remove = e.target.closest('[data-collection-remove]');
    const report = e.target.closest('[data-collection-report]');
    const describe = e.target.closest('[data-describe-collection]');
    try {
      if (describe) {
        describe.disabled = true;
        const r = await api('knowledge/describe-pictures', {collection: describe.dataset.describeCollection});
        notice(`The adviser will describe the pictures of ${plural(r.queued.length, 'document')} in its own conversation.`);
        refresh();
      }
      if (update) {
        update.disabled = true;
        await api('knowledge/update', {id: update.dataset.collectionUpdate});
        notice('Importing again. Only changed files are read again.');
        refresh();
      }
      if (remove) {
        remove.disabled = true;
        const r = await api('knowledge/collection-remove', {id: remove.dataset.collectionRemove});
        notice(`Removed from HA (${r.copies_removed} imported copies). The folder or repository itself is unchanged.`);
        refresh();
      }
      if (report) {
        const r = await api('knowledge/report', {id: report.dataset.collectionReport});
        report.closest('details').querySelector('ul').innerHTML = r.skipped.map(x => `<li>${esc(x.path)}: ${esc(x.reason)}</li>`).join('');
        report.remove();
      }
    } catch (x) {
      notice(x.message, true);
      if (update) update.disabled = false;
      if (remove) remove.disabled = false;
    }
  });
  sources.addEventListener('click', async e => {
    const describe = e.target.closest('[data-describe-source]');
    if (!describe) return;
    describe.disabled = true;
    try {
      await api('knowledge/describe-pictures', {source: describe.dataset.describeSource});
      notice('The adviser will describe these pictures in its own conversation.');
      refresh();
    } catch (x) {
      notice(x.message, true);
      describe.disabled = false;
    }
  });
  collections.addEventListener('change', async e => {
    const input = e.target.closest('[data-collection-setting]');
    if (!input) return;
    const id = input.closest('[data-collection]').dataset.collection;
    const key = input.dataset.collectionSetting;
    const value = input.type === 'checkbox' ? input.checked : Number(input.value);
    try {
      await api('knowledge/collection-settings', {id, settings: {[key]: value}});
      notice(key === 'external_allowed' ? 'Saved. Importing again to apply it.' : 'Saved.');
      refresh();
    } catch (x) {
      notice(x.message, true);
    }
  });
})();
