'use strict';
// Back up a folder to GitHub: the form, and each saved backup with its progress.
(() => {
  const form = document.querySelector('#folder-backup-form');
  const list = document.querySelector('#folder-backup-list');
  if (!form || !list) return;
  const field = name => form.elements[name];
  const EVERY = {15: 'Every 15 minutes', 60: 'Every hour', 360: 'Every 6 hours', 1440: 'Once a day'};
  function showCreateOnly() {
    document.querySelector('#folder-backup-visibility').hidden = field('action').value !== 'create';
  }
  field('action').addEventListener('change', showCreateOnly);
  showCreateOnly();
  field('name').addEventListener('input', () => {
    const v = field('name').value;
    if (v.includes('/')) {
      const [owner, ...rest] = v.split('/');
      field('owner').value = owner;
      field('name').value = rest.join('/');
    }
  });
  // A sensible repository name from the folder's own name.
  field('folder').addEventListener('input', () => {
    if (field('name').value) return;
    const base = field('folder').value.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '';
    field('name').value = base.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 100);
  });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const button = form.querySelector('button.primary');
    button.disabled = true;
    try {
      const f = Object.fromEntries(new FormData(form));
      const request = {
        folder: f.folder, action: f.action, name: f.name, owner: f.owner,
        description: f.description, automatic: f.automatic === 'on',
        interval_minutes: Number(f.interval_minutes), include_deletions: f.include_deletions === 'on',
      };
      if (f.action === 'create') request.visibility = f.visibility;
      await api('folders/add', request);
      notice('Backing up the folder. Progress shows below.');
      form.reset();
      showCreateOnly();
      refresh();
    } catch (x) {
      notice(x.message, true);
    } finally {
      button.disabled = false;
    }
  });
  function signature(items) {
    return JSON.stringify(items.map(b => [b.id, b.owner, b.name, b.visibility, b.automatic, b.interval_minutes,
      b.include_deletions, b.running, b.state, (b.excluded || []).length, b.url || '']));
  }
  function card(b) {
    const where = b.owner ? `${b.owner}/${b.name}` : b.name;
    const link = b.url ? `<a href="${esc(b.url)}" target="_blank" rel="noopener noreferrer">${esc(where)}</a>` : esc(where);
    const visibility = b.visibility ? ` · ${b.visibility === 'public' ? 'Public' : 'Private'}` : '';
    const excluded = (b.excluded || []).length
      ? `<details><summary>Left out (${b.excluded.length})</summary><ul class="plain">${b.excluded.map(x => `<li>${esc(x.path)}: ${esc(x.reason)}</li>`).join('')}</ul></details>`
      : '';
    const every = Object.entries(EVERY).map(([v, label]) => `<option value="${v}"${Number(v) === b.interval_minutes ? ' selected' : ''}>${label}</option>`).join('');
    return `<details open data-backup="${esc(b.id)}"><summary>${link}${visibility} ${badge(b.running ? 'uploading' : b.state)}</summary>
      <p class="muted">${esc(b.folder)}</p>
      <progress max="100" class="fb-bar"${b.running ? '' : ' hidden'}></progress>
      <p class="fb-message"></p>
      ${excluded}
      <label class="check"><input type="checkbox" data-backup-setting="automatic"${b.automatic ? ' checked' : ''}>Upload changes automatically</label>
      <label>How often<select data-backup-setting="interval_minutes">${every}</select></label>
      <label class="check"><input type="checkbox" data-backup-setting="include_deletions"${b.include_deletions ? ' checked' : ''}>Also remove files I delete here (they stay in GitHub's history)</label>
      <div class="actions"><button type="button" data-backup-upload="${esc(b.id)}"${b.running ? ' disabled' : ''}>Upload now</button><button type="button" data-backup-remove="${esc(b.id)}"${b.running ? ' disabled' : ''}>Stop backing up</button></div>
    </details>`;
  }
  window.renderFolderBackups = s => {
    const items = s.folder_backups || [];
    const sig = signature(items);
    if (list.dataset.sig !== sig) {
      list.dataset.sig = sig;
      list.innerHTML = items.map(card).join('') || '<p class="empty">No folders backed up yet.</p>';
    }
    for (const b of items) {
      const el = list.querySelector(`[data-backup="${CSS.escape(b.id)}"]`);
      if (!el) continue;
      const bar = el.querySelector('.fb-bar');
      if (b.progress) {
        bar.hidden = false;
        bar.value = b.progress.percent;
      } else bar.hidden = !b.running;
      const when = b.last_upload ? ` Last upload: ${new Date(b.last_upload * 1000).toLocaleString()}.` : '';
      el.querySelector('.fb-message').textContent = (b.progress ? b.progress.text : b.message || '') + (b.running ? '' : when);
    }
  };
  list.addEventListener('click', async e => {
    const upload = e.target.closest('[data-backup-upload]');
    const remove = e.target.closest('[data-backup-remove]');
    if (!upload && !remove) return;
    const button = upload || remove;
    button.disabled = true;
    try {
      if (upload) {
        await api('folders/upload', {id: upload.dataset.backupUpload});
        notice('Uploading changes.');
      } else {
        await api('folders/remove', {id: remove.dataset.backupRemove});
        notice('Stopped backing up this folder. The folder and the copy on GitHub are unchanged.');
      }
      refresh();
    } catch (x) {
      notice(x.message, true);
      button.disabled = false;
    }
  });
  list.addEventListener('change', async e => {
    const input = e.target.closest('[data-backup-setting]');
    if (!input) return;
    const id = input.closest('[data-backup]').dataset.backup;
    const key = input.dataset.backupSetting;
    const value = input.type === 'checkbox' ? input.checked : Number(input.value);
    try {
      await api('folders/settings', {id, settings: {[key]: value}});
      notice('Saved.');
      refresh();
    } catch (x) {
      notice(x.message, true);
    }
  });
})();
