'use strict';
// Keep editor state separate from periodic status rendering. Never replace a draft.
(() => {
  let state, selected = '', opened = null, dirty = false, busy = false, generation = 0;
  let listing = null, signature = '', pendingJob = null, openGeneration = 0;
  const byId = id => document.getElementById(id);
  const message = (text, error = false) => {
    byId('workspace-message').textContent = text;
    byId('workspace-message').className = error ? 'workspace-error' : 'muted';
  };
  const guarded = fn => async (...args) => {
    try { await fn(...args); } catch (e) { message(e.message, true); }
  };
  const requireClean = () => {
    if (busy) throw Error('Wait for the current file operation to finish.');
    if (dirty) throw Error('Save your draft or choose Discard draft before changing files or running checks.');
  };
  function controls() {
    const editable = !!selected && listing?.editable && !busy;
    byId('file-save').disabled = !editable || !opened || byId('file-editor').hidden;
    byId('file-upload').disabled = !editable;
    byId('file-new').disabled = !editable;
    byId('workspace-check').disabled = !editable || !!pendingJob;
    byId('file-editor').readOnly = !editable;
    byId('file-draft').textContent = dirty ? 'Unsaved draft' : opened ? 'Saved on disk' : '';
    byId('file-discard').disabled = !dirty || busy;
  }
  function clearEditor() {
    opened = null; dirty = false;
    byId('file-path').value = ''; byId('file-editor').value = '';
    byId('file-editor').hidden = true; byId('file-binary').hidden = true;
    byId('file-metadata').textContent = 'Select a file, upload a target, or create a text file.';
    controls();
  }
  async function listFiles(force = false) {
    if (!selected) return;
    const task = selected, seq = ++generation;
    const data = await api('workspace/list', {task});
    if (seq !== generation || task !== selected) return;
    listing = data;
    byId('workspace-location').textContent = data.root;
    byId('workspace-readiness').textContent = data.reason || 'Paused and ready to edit. Independent checks leave the task paused.';
    byId('workspace-files').innerHTML = data.files.map(f => `<button type="button" data-file="${esc(f.path)}" class="file-entry"><span>${esc(f.path)}</span><small>${f.size.toLocaleString()} B</small></button>`).join('') || '<p class="muted">No files yet.</p>';
    if (data.truncated) byId('workspace-files').insertAdjacentHTML('beforeend', '<p>First 2,000 files shown. Enter a relative path to open another file.</p>');
    byId('workspace-files').querySelectorAll('[data-file]').forEach(b => b.onclick = guarded(() => openFile(b.dataset.file)));
    controls();
  }
  async function openFile(path) {
    requireClean();
    const task = selected, seq = ++openGeneration;
    const file = await api('workspace/read', {task, path});
    // A pending read must not overwrite a draft started while it was in flight.
    if (task !== selected || dirty || seq !== openGeneration || busy) return;
    opened = file; byId('file-path').value = file.path;
    byId('file-editor').hidden = file.text === null;
    byId('file-editor').value = file.text ?? '';
    byId('file-binary').hidden = file.text !== null;
    byId('file-binary').textContent = file.preview_hex || '';
    byId('file-metadata').textContent = `${file.size.toLocaleString()} bytes · SHA-256 ${file.sha256}${file.text === null ? ' · Binary or large file: first 256 bytes shown.' : ''}`;
    controls();
  }
  async function selectTask(task) {
    requireClean();
    selected = task; signature = ''; listing = null; generation++;
    byId('workspace-task').value = task; clearEditor();
    byId('workspace-result-summary').textContent = 'No check result loaded. Run checks or view the last retained result.';
    byId('workspace-result').textContent = '';
    for (const id of ['target-task','acceptance-task','native-test-task','goal-task','repository-task','hosted-test-task']) {
      if (byId(id)) byId(id).value = task;
    }
    if (task) await listFiles(true);
  }
  function showResult(report) {
    const result = report.result || report;
    byId('workspace-result-summary').textContent = result.status === 'not_run' ? 'No checks have run yet.' :
      `${result.passed === true ? 'Checks passed' : 'Checks did not pass'}${report.revision !== undefined ? ' at project revision ' + report.revision : ''}. ${result.claim || result.reason || 'See the retained observations below.'} This is a check result; it does not complete the agent task.`;
    byId('workspace-result').textContent = JSON.stringify(report, null, 2);
  }
  window.renderWorkspace = s => {
    state = s;
    byId('app-version').textContent = 'Ghidra + REA · v' + s.version;
    byId('native-readiness').textContent = `${s.routes.filter(r => r.status.ready).length} of ${s.routes.length} native routes observed ready. Autonomous work also requires sufficient allowance and installed foundations. You can edit files and run configured local checks now.`;
    const select = byId('workspace-task');
    const options = s.tasks.map(t => `<option value="${esc(t.id)}">${esc(s.projects.find(p => p.id === t.project_id)?.name || t.id)} · ${esc(t.objective.slice(0,65))} · ${esc(t.status)}</option>`).join('');
    if (select.innerHTML !== options) { select.innerHTML = options; select.value = selected; }
    if (!selected && s.tasks.length) guarded(() => selectTask(s.tasks[0].id))();
    const t = s.tasks.find(t => t.id === selected);
    const key = t ? [selected, s.projects.find(p => p.id === t.project_id)?.revision, t.status, t.owner].join(':') : '';
    if (key && key !== signature) { signature = key; guarded(listFiles)(); }
    if (pendingJob) {
      const job = s.jobs[pendingJob.id];
      if (job && job.status !== 'running') {
        const task = pendingJob.task; pendingJob = null;
        if (selected === task) {
          if (job.status === 'failed') message(job.error, true);
          else { showResult(job.result); message('Checks finished. The task remains paused.'); }
        } else notice('Project checks finished. Select the project and view its last result.');
        controls();
      }
    }
  };
  byId('workspace-task').onchange = guarded(async e => {
    const next = e.target.value; e.target.value = selected; await selectTask(next);
  });
  byId('workspace-refresh').onclick = guarded(listFiles);
  byId('file-open-form').onsubmit = guarded(async e => { e.preventDefault(); await openFile(byId('file-path').value.trim()); });
  byId('file-editor').oninput = () => { dirty = true; controls(); };
  byId('file-new').onclick = guarded(() => {
    requireClean();
    const path = byId('file-path').value.trim();
    if (!path) throw Error('Enter a relative filename above, such as src/candidate.py.');
    if (listing.files.some(f => f.path === path)) throw Error('This file exists. Open it before editing.');
    opened = {path, sha256:null}; dirty = true;
    byId('file-editor').value = ''; byId('file-editor').hidden = false; byId('file-binary').hidden = true;
    byId('file-metadata').textContent = 'New file · ' + path; controls(); byId('file-editor').focus();
  });
  byId('file-save').onclick = guarded(async () => {
    if (!opened) return;
    const task = selected, path = opened.path, text = byId('file-editor').value;
    busy = true; controls();
    try {
      const result = await api('workspace/write', {task,path,text,expected_sha:opened.sha256});
      opened.sha256 = result.sha256; dirty = false;
      message('Saved ' + path + '. Previous contents were retained. Rerun checks for this version.');
      byId('workspace-result-summary').textContent = 'Files changed. Rerun checks to verify the current version.';
      await listFiles();
    } finally { busy = false; controls(); }
  });
  byId('file-discard').onclick = guarded(async () => {
    const path = opened?.path, isNew = opened?.sha256 === null;
    dirty = false; clearEditor(); if (path && !isNew) await openFile(path);
  });
  byId('file-upload').onchange = guarded(async e => {
    requireClean();
    const files = [...e.target.files]; const task = selected;
    busy = true; controls();
    try {
      for (const file of files) {
        if (file.size > 256 * 1024 * 1024) throw Error(file.name + ' exceeds 256 MiB. Use local target import for larger files.');
        if (listing.files.some(f => f.path === file.name)) throw Error(file.name + ' already exists. Upload with a different filename to preserve it.');
        message('Uploading ' + file.name + '…');
        const r = await fetch('/api/workspace/upload', {method:'POST',headers:{'X-Workbench-Token':token||'','Content-Type':'application/octet-stream','X-HA-Task':task,'X-HA-Path':encodeURIComponent(file.name)},body:file});
        const result = await r.json(); if (!r.ok) throw Error(result.error || 'Upload failed');
      }
      message('Files uploaded. Configure acceptance checks in Projects & tasks before starting agents.');
    } finally { e.target.value = ''; busy = false; await listFiles(); controls(); }
  });
  byId('workspace-check').onclick = guarded(async () => {
    requireClean(); busy = true; controls();
    try {
      const job = await api('project/check', {task:selected});
      pendingJob = {id:job.job, task:selected};
      byId('workspace-result-summary').textContent = 'Running independent checks…';
      message('Checks are running. Results will appear here.');
    } finally { busy = false; controls(); }
    refresh();
  });
  byId('workspace-last-result').onclick = guarded(async () => {
    const task = selected, result = await api('project/check-result', {task});
    if (task === selected) showResult(result);
  });
  byId('workspace-pause').onclick = guarded(async () => { await api('control', {task:selected,action:'pause'}); await refresh(); await listFiles(); });
  byId('workspace-suite').onclick = guarded(async () => {
    requireClean(); const file = await api('workspace/read', {task:selected,path:'suite.json'});
    if (file.text === null) throw Error('suite.json must be a UTF-8 text file.');
    JSON.parse(file.text); byId('native-test-task').value = selected;
    document.querySelector('#native-test-form [name=suite]').value = file.text;
    tab('projects'); byId('native-test-form').scrollIntoView({behavior:'smooth'});
  });
  document.querySelectorAll('[data-starter]').forEach(b => b.onclick = guarded(async () => {
    requireClean(); const kind = b.dataset.starter;
    const allow = byId('starter-native-allow').checked;
    if (kind === 'native_python' && !allow) throw Error('Authorize the supplied Python example using the checkbox first.');
    b.disabled = true;
    const key = 'ha-starter-request-' + kind;
    const request = sessionStorage.getItem(key) || crypto.randomUUID(); sessionStorage.setItem(key, request);
    try {
      const task = await api('project/starter', {kind,request_id:request,allow_native:allow});
      sessionStorage.removeItem(key); await refresh(); await selectTask(task.id); tab('workspace');
      await openFile(kind === 'registers' ? 'candidate.hex' : 'candidate.py');
      message('Example ready. Run checks, edit the candidate, and check again.');
    } finally { b.disabled = false; }
  }));
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  controls();
})();
