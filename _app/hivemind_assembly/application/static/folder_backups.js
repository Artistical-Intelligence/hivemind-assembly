'use strict';
// Back up a folder to GitHub: the form, and each saved backup with its progress,
// its large files (release assets or Git LFS) and what was left out.
(() => {
  const form = document.querySelector('#folder-backup-form');
  const list = document.querySelector('#folder-backup-list');
  if (!form || !list) return;
  const field = name => form.elements[name];
  const EVERY = {15: 'Every 15 minutes', 60: 'Every hour', 360: 'Every 6 hours', 1440: 'Once a day'};
  const size = n => n >= 1073741824 ? (n / 1073741824).toFixed(1) + ' GiB' : n >= 1048576 ? (n / 1048576).toFixed(0) + ' MiB' : n + ' bytes';
  function showCreateOnly() {
    const creating = field('action').value === 'create';
    document.querySelector('#folder-backup-visibility').hidden = !creating;
    document.querySelector('#folder-backup-public-note').hidden = !(creating && field('visibility').value === 'public');
  }
  field('action').addEventListener('change', showCreateOnly);
  field('visibility').addEventListener('change', showCreateOnly);
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
  const nameFromFolder = path => (path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '')
    .replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 100);
  field('folder').addEventListener('input', () => {
    if (field('name').value) return;
    field('name').value = nameFromFolder(field('folder').value);
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
        lfs: f.lfs === 'on',
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
  const STATUS = {
    uploaded: f => f.parts > 1 ? `uploaded in ${f.parts} parts` : 'uploaded',
    lfs: () => 'stored with Git LFS',
    waiting: () => 'waiting: connect GitHub to upload this file',
    failed: f => 'failed: ' + (f.message || 'see the message above'),
    checking: f => `checking, ${f.percent || 0}%`,
    uploading: f => `uploading, ${f.percent || 0}%` + (f.parts > 1 ? ` (${f.parts} parts)` : ''),
  };
  const statusText = f => (STATUS[f.status] || (() => f.status))(f);
  function signature(items) {
    return JSON.stringify(items.map(b => [b.id, b.owner, b.name, b.visibility, b.visibility_notice || '', b.automatic,
      b.interval_minutes, b.include_deletions, b.lfs, b.running, b.state, (b.excluded || []).length, b.url || '',
      (b.large_files || []).map(f => f.path)]));
  }
  function largeList(b) {
    const items = b.large_files || [];
    if (!items.length) return '';
    const open = items.some(f => f.status !== 'uploaded' && f.status !== 'lfs') ? ' open' : '';
    const pub = b.visibility === 'public' && items.some(f => f.status !== 'lfs')
      ? '<p class="muted">This repository is public, so its release assets (the large files) are public too.</p>' : '';
    return `<details class="fb-large"${open}><summary>Large files (${items.length})</summary>${pub}<ul class="plain">${items.map(f =>
      `<li data-large="${esc(f.path)}">${esc(f.path)} <span class="muted">${size(f.size)}</span>: <span class="fb-large-status">${esc(statusText(f))}</span></li>`).join('')}</ul>
      <p class="muted">${items.some(f => f.status !== 'lfs') ? 'To get them back, run restore-large-files.ps1 (Windows) or restore_large_files.py from a copy of the repository.' : 'Git LFS gives them back when the repository is cloned.'}</p></details>`;
  }
  function card(b) {
    const where = b.owner ? `${b.owner}/${b.name}` : b.name;
    const link = b.url ? `<a href="${esc(b.url)}" target="_blank" rel="noopener noreferrer">${esc(where)}</a>` : esc(where);
    const visibility = b.visibility ? ` · ${b.visibility === 'public' ? 'Public' : 'Private'}` : '';
    const changed = b.visibility_notice ? `<p class="alert" role="status">${esc(b.visibility_notice)} HA keeps uploading to it.</p>` : '';
    const excluded = (b.excluded || []).length
      ? `<details><summary>Left out (${b.excluded.length})</summary><ul class="plain">${b.excluded.map(x => `<li>${esc(x.path)}: ${esc(x.reason)}${x.separate
        ? ` <button type="button" data-backup-separately="${esc(x.separate)}">Back up this folder separately</button>` : ''}</li>`).join('')}</ul></details>`
      : '';
    const every = Object.entries(EVERY).map(([v, label]) => `<option value="${v}"${Number(v) === b.interval_minutes ? ' selected' : ''}>${label}</option>`).join('');
    return `<details open data-backup="${esc(b.id)}"><summary>${link}${visibility} ${badge(b.running ? 'uploading' : b.state)}</summary>
      <p class="muted">${esc(b.folder)}</p>
      ${changed}
      <progress max="100" class="fb-bar"${b.running ? '' : ' hidden'}></progress>
      <p class="fb-message"></p>
      ${largeList(b)}
      ${excluded}
      <label class="check"><input type="checkbox" data-backup-setting="automatic"${b.automatic ? ' checked' : ''}>Upload changes automatically</label>
      <label>How often<select data-backup-setting="interval_minutes">${every}</select></label>
      <label class="check"><input type="checkbox" data-backup-setting="include_deletions"${b.include_deletions ? ' checked' : ''}>Also remove files I delete here (they stay in GitHub's history)</label>
      <label class="check"><input type="checkbox" data-backup-setting="lfs"${b.lfs ? ' checked' : ''}${!b.lfs && !lfsInstalled ? ' disabled' : ''}>Store large files with Git LFS instead${!lfsInstalled ? " (Git LFS isn't installed)" : ''}</label>
      <div class="actions"><button type="button" data-backup-upload="${esc(b.id)}"${b.running ? ' disabled' : ''}>Upload now</button><button type="button" data-backup-remove="${esc(b.id)}"${b.running ? ' disabled' : ''}>Stop backing up</button></div>
    </details>`;
  }
  let lfsInstalled = true;
  window.renderFolderBackups = s => {
    lfsInstalled = s.git_lfs !== false;
    const lfsBox = document.querySelector('#folder-backup-lfs');
    lfsBox.disabled = !lfsInstalled;
    document.querySelector('#folder-backup-lfs-note').dataset.missing = lfsInstalled ? '' : '1';
    if (!lfsInstalled) lfsBox.checked = false;
    lfsBox.closest('label').title = lfsInstalled ? '' : "Git LFS isn't installed on this computer.";
    const items = s.folder_backups || [];
    const sig = signature(items) + lfsInstalled;
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
      // Each large file's status and percentage, updated in place while uploading.
      for (const f of b.large_files || []) {
        const row = el.querySelector(`[data-large="${CSS.escape(f.path)}"] .fb-large-status`);
        if (row) row.textContent = statusText(f);
      }
    }
  };
  list.addEventListener('click', async e => {
    const separate = e.target.closest('[data-backup-separately]');
    if (separate) {
      // A folder with its own Git history: start a backup of just that folder.
      form.reset();
      field('folder').value = separate.dataset.backupSeparately;
      field('name').value = nameFromFolder(separate.dataset.backupSeparately);
      showCreateOnly();
      form.scrollIntoView({behavior: 'smooth', block: 'start'});
      field('name').focus();
      notice('The form is filled in for that folder. Check it, then select Back up folder.');
      return;
    }
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
      notice(key === 'lfs' ? (value ? 'Saved. The next upload stores large files with Git LFS.' : 'Saved. The next upload backs up large files as release assets.') : 'Saved.');
      refresh();
    } catch (x) {
      notice(x.message, true);
      input.checked = !input.checked;
    }
  });
})();
