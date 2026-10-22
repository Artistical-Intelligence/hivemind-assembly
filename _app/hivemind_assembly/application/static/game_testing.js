'use strict';
// Owner play-testing panel. Every input is recorded as a trajectory token, so any
// session or finding replays exactly. All labels are text; frames are drawn from raw
// RGBA on canvas (no image URLs), like the capture viewer.
(() => {
  const byId = id => document.getElementById(id);
  let spec = null, task = '', token = '', history = [], pending = null, busy = false, findings = [];
  const side = () => byId('game-side').value;
  const gamePath = () => byId('game-path').value.trim() || 'game.json';
  const status = (text, error = false) => {
    byId('game-status').textContent = text;
    byId('game-status').className = error ? 'workspace-error' : 'muted';
  };
  const guarded = fn => async (...args) => {
    try { await fn(...args); } catch (e) { status(e.message, true); } finally { controls(); }
  };
  function controls() {
    const ready = !!spec && !busy;
    for (const id of ['game-restart', 'game-explore', 'game-compare', 'game-regressions', 'game-save']) byId(id).disabled = !ready || (!!pending && id !== 'game-restart');
    byId('game-undo').disabled = !ready || !history.length;
    byId('game-load').disabled = busy;
    byId('game-actions').querySelectorAll('button').forEach(b => b.disabled = !ready);
    byId('game-findings').querySelectorAll('button').forEach(b => b.disabled = !ready || !!pending);
  }
  function drawFrame(frame, parent) {
    const figure = document.createElement('figure');
    const canvas = document.createElement('canvas');
    canvas.width = frame.width; canvas.height = frame.height;
    canvas.className = 'game-canvas';
    const scale = Math.max(1, Math.min(24, Math.floor(320 / Math.max(frame.width, frame.height))));
    canvas.style.width = frame.width * scale + 'px';
    canvas.style.height = frame.height * scale + 'px';
    const raw = atob(frame.rgba_base64);
    if (raw.length === frame.width * frame.height * 4) {
      const context = canvas.getContext('2d');
      const image = context.createImageData(frame.width, frame.height);
      for (let i = 0; i < raw.length; i++) image.data[i] = raw.charCodeAt(i);
      context.putImageData(image, 0, 0);
    }
    const caption = document.createElement('figcaption');
    caption.textContent = `${frame.side} · tick ${frame.tick}`;
    figure.append(canvas, caption);
    parent.append(figure);
  }
  function showFrames(frames) {
    const target = byId('game-frames');
    target.replaceChildren();
    // Results list the newest ticks first; show them in time order.
    const ordered = [...(frames || [])].sort((a, b) => a.tick - b.tick || a.side.localeCompare(b.side));
    for (const frame of ordered) drawFrame(frame, target);
    if (!target.children.length) {
      const note = document.createElement('p');
      note.className = 'muted';
      note.textContent = 'No frame yet. Play an action to advance the game.';
      target.append(note);
    }
  }
  function summary(observation) {
    const problems = (observation.problems || []).map(p => p.signature.join(' ')).join(', ');
    return `${observation.side}: ${observation.status}, ${observation.ticks} ticks${problems ? ' · problems: ' + problems : ''}`;
  }
  function outcomeText(result) {
    if (result.outcome === 'limit') return 'Outcome limit (inconclusive: a harness bound stopped the run).';
    if (result.outcome === 'cancelled') return 'Outcome cancelled (inconclusive).';
    return `Outcome ${result.outcome}.`;
  }
  function render(result) {
    showFrames(result.frames);
    if (result.outcome === 'unreached') {
      status('The start preconditions were not met: outcome unreached.', true);
      byId('game-state').textContent = JSON.stringify(result.preconditions, null, 2);
      return;
    }
    if (result.side === 'both') {
      byId('game-state').textContent = JSON.stringify({original: result.original.state, candidate: result.candidate.state}, null, 2);
      const divergence = result.comparison.divergence;
      status(`${outcomeText(result)} ${summary(result.original)}. ${summary(result.candidate)}.` +
        (divergence ? ` First divergence at tick ${divergence.tick}: ${divergence.signature.join(' ')}.` : ' No divergence so far.'));
    } else {
      byId('game-state').textContent = JSON.stringify(result.observation.state, null, 2);
      status(`${outcomeText(result)} ${summary(result.observation)}. ${history.length} actions recorded.`);
    }
    byId('game-result').textContent = JSON.stringify(result, null, 2);
  }
  async function play(actions = []) {
    busy = true; controls();
    try {
      const result = await api('game/play', {task, game_path: gamePath(), side: side(), trajectory: token, actions, images: 1});
      if (result.outcome === 'unsupported') throw Error('The candidate did not build: ' + JSON.stringify(result.build).slice(0, 400));
      if (actions.length) history.push(token);
      token = result.trajectory || token;
      render(result);
    } finally { busy = false; controls(); }
  }
  function renderActions() {
    const target = byId('game-actions');
    target.replaceChildren();
    for (const [name, action] of Object.entries(spec.game.actions)) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.gameAction = name;
      button.textContent = `${name.replaceAll('_', ' ')} (${action.ticks})`;
      button.onclick = guarded(() => play([name]));
      target.append(button);
    }
  }
  function renderFindings(items, note, testedSide) {
    // Each finding keeps the side it was found on, so Shrink and Package replay it
    // on the same build(s), and whether it needs end of input.
    findings = items.map(item => ({...item, testedSide: item.testedSide || testedSide}));
    const target = byId('game-findings');
    target.replaceChildren();
    const intro = document.createElement('p');
    intro.textContent = note;
    target.append(intro);
    findings.forEach((finding, index) => {
      const row = document.createElement('div');
      row.className = 'game-finding';
      const text = document.createElement('p');
      const original = finding.original_behavior ? ' · original behavior (also in the original)' : '';
      text.textContent = `${finding.signature.join(' ')} at tick ${finding.tick}${finding.minimized_ticks ? ' · ' + finding.minimized_ticks + ' inputs' : ''}${finding.after_end ? ' · after end of input' : ''}${original}`;
      row.append(text);
      for (const [label, key] of [['Replay', 'gameReplay'], ['Shrink', 'gameShrink'], ['Bug package', 'gamePackage'], ['Save as regression', 'gameSave']]) {
        if (finding.original_behavior && key === 'gameShrink') continue;
        const button = document.createElement('button');
        button.type = 'button'; button.textContent = label; button.dataset[key] = String(index);
        row.append(button);
      }
      target.append(row);
    });
    target.querySelectorAll('[data-game-replay]').forEach(b => b.onclick = guarded(async () => {
      const finding = findings[Number(b.dataset.gameReplay)];
      byId('game-side').value = finding.testedSide || (spec.sides.original.available && spec.sides.candidate.available ? 'both' : 'candidate');
      token = finding.trajectory; history = [];
      await play([]);
    }));
    target.querySelectorAll('[data-game-shrink]').forEach(b => b.onclick = guarded(() => {
      const finding = findings[Number(b.dataset.gameShrink)];
      return startTest({mode: 'shrink', side: finding.testedSide, trajectory: finding.trajectory, signature: finding.signature, end: !!finding.after_end});
    }));
    target.querySelectorAll('[data-game-package]').forEach(b => b.onclick = guarded(() => {
      const finding = findings[Number(b.dataset.gamePackage)];
      return startTest({mode: 'package', side: finding.testedSide, trajectory: finding.trajectory, signature: finding.signature, images: 2, end: !!finding.after_end});
    }));
    target.querySelectorAll('[data-game-save]').forEach(b => b.onclick = guarded(() => {
      const finding = findings[Number(b.dataset.gameSave)];
      return saveRegression(finding.trajectory, finding.signature.join('-'), finding.original_behavior ? 'Original behavior kept as a regression.' : 'Found by play-testing.', !!finding.after_end);
    }));
    controls();
  }
  async function saveRegression(trajectory, label, note, end = true) {
    const id = (label.replace(/[^A-Za-z0-9_.-]+/g, '_').slice(0, 40) + '-' + Date.now().toString(36)).replace(/^[^A-Za-z0-9]+/, 'r');
    const expect = spec.sides.original.available ? 'match_original' : 'no_problems';
    await api('game/save-regression', {task, game_path: gamePath(), trajectory, id, expect, note, end});
    status(`Saved regression ${id} (${expect.replace('_', ' ')}). Run saved regressions after each change.`);
  }
  async function startTest(args) {
    if (pending) throw Error('Wait for the running game test to finish.');
    const clean = Object.fromEntries(Object.entries(args).filter(([, v]) => v !== undefined));
    const job = await api('game/test', {task, game_path: gamePath(), ...clean});
    pending = {id: job.job, mode: args.mode, task, side: clean.side};
    status(`Running ${args.mode}…`);
    controls();
    refresh();
  }
  function finish(mode, result, testedSide) {
    byId('game-result').textContent = JSON.stringify(result, null, 2);
    if (result.outcome === 'unsupported') { status('The candidate did not build; see the full result.', true); return; }
    if (mode === 'explore') {
      const items = [...result.findings, ...result.original_behavior.map(q => ({...q, original_behavior: true}))];
      const cut = result.outcome === 'limit' || result.outcome === 'cancelled' ? ` Stopped early (${result.stopped}); the outcome is inconclusive.` : '';
      renderFindings(items, `Explored ${result.steps_run} steps (${result.ticks_executed} ticks, ${result.cells} situations, seed ${result.seed}, ${result.mode}). ${result.findings.length} findings; ${result.original_behavior.length} also occur in the original.${cut}`, result.side);
      status(`Exploration outcome: ${result.outcome}.`, result.outcome === 'limit' || result.outcome === 'cancelled');
    } else if (mode === 'shrink') {
      if (!result.reproduced) { status('The finding did not reproduce from its trajectory.', true); return; }
      renderFindings([{...result.problem, trajectory: result.trajectory, minimized_ticks: result.minimized_ticks, after_end: result.end}], `Shrunk from ${result.original_ticks} to ${result.minimized_ticks} inputs in ${result.tests} replays: ${result.controls.join(', ')}. Confirmed on fresh engines: ${result.confirmed ? 'yes' : 'no'}.`, testedSide || result.side);
      status('Shrinking finished.');
    } else if (mode === 'package') {
      showFrames(result.frames);
      byId('game-state').textContent = JSON.stringify(result.state_window, null, 2);
      status(result.reproduced ? `Bug package: ${result.outcome} at tick ${result.problem.tick}. Frames show the ticks just before and at the failure.` : 'The finding did not reproduce.');
    } else if (mode === 'regressions') {
      status(result.total ? `Saved regressions: ${result.total - result.failed.length} of ${result.total} passed${result.failed.length ? '; failed or inconclusive: ' + result.failed.join(', ') : ''}.` : 'No saved regressions yet.', !result.passed);
    } else {
      showFrames(result.frames);
      status(`Comparison outcome: ${result.outcome}${result.divergence ? ', first divergence at tick ' + result.divergence.tick + ' (' + result.divergence.signature.join(' ') + ')' : ''}.`, !result.passed);
    }
  }
  window.renderGameTesting = s => {
    if (!pending || pending.fetching) return;
    const job = s.jobs[pending.id];
    if (!job || job.status === 'running') return;
    const current = pending;
    current.fetching = true;
    // Status polls omit frames; fetch the complete result once.
    api('jobs/result', {job: current.id}).then(full => {
      if (pending !== current) return;
      pending = null;
      if (current.task !== task) { status('A game test for another project finished; load that project again to see its findings.'); return; }
      if (full.status === 'failed') status(full.error, true);
      else finish(current.mode, full.result, current.side);
    }).catch(e => {
      if (pending === current) pending = null;
      status(e.message, true);
    }).finally(controls);
  };
  byId('game-load').onclick = guarded(async () => {
    const chosen = byId('workspace-task').value;
    if (!chosen) throw Error('Create or select a project first.');
    task = chosen;
    spec = null; token = ''; history = []; findings = [];
    byId('game-findings').replaceChildren();
    busy = true; controls();
    try { spec = await api('game/describe', {task, game_path: gamePath()}); } finally { busy = false; }
    if (!spec.sides.original.available && side() !== 'candidate') byId('game-side').value = 'candidate';
    if (!spec.sides.candidate.available && spec.sides.original.available) byId('game-side').value = 'original';
    renderActions();
    const broken = spec.regressions_error ? ` Regressions file problem: ${spec.regressions_error}.` : '';
    byId('game-description').textContent = `${spec.game.name}: ${spec.game.fields.length} state fields, ${spec.game.rules.length} rules, ${spec.regressions} saved regressions. Candidate ${spec.sides.candidate.available ? 'ready' : 'unavailable'}; original ${spec.sides.original.available ? 'ready' : 'unavailable'}.${broken}`;
    await play([]);
  });
  byId('game-side').onchange = guarded(() => spec && play([]));
  byId('game-restart').onclick = guarded(() => { token = ''; history = []; return play([]); });
  byId('game-undo').onclick = guarded(async () => {
    if (!history.length) return;
    const saved = history.slice(), current = token;
    token = history[history.length - 1];
    history = [];
    try {
      await play([]);
      history = saved.slice(0, -1);
    } catch (error) {
      // Keep the session where it was if replaying the earlier trajectory fails.
      history = saved; token = current;
      throw error;
    }
  });
  byId('game-explore').onclick = guarded(() => startTest({
    mode: 'explore',
    side: side() === 'original' ? 'original' : side() === 'both' ? 'both' : 'candidate',
    steps: Number(byId('game-steps').value) || 200,
    seed: Number(byId('game-seed').value) || 0,
    seconds: 300,
  }));
  byId('game-compare').onclick = guarded(() => startTest({mode: 'compare', trajectory: token}));
  byId('game-regressions').onclick = guarded(() => startTest({mode: 'regressions', seconds: 300}));
  byId('game-save').onclick = guarded(() => saveRegression(token, 'play', 'Saved from manual play.'));
  controls();
})();
