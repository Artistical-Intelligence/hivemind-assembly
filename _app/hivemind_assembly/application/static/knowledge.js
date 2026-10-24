'use strict';
(() => {
  let catalogRevision = '';
  const learningForm = document.querySelector('#experimental-settings');
  let learningDirty = false;
  learningForm.addEventListener('input', () => {learningDirty = true;});
  const tags = value => value.split(',').map(x => x.trim()).filter(Boolean);
  function options(select, items) {
    const prior = select.value;
    const signature = JSON.stringify(items);
    if (select.dataset.items === signature) return;
    select.replaceChildren(...items.map(([value, label]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = label; return option;
    }));
    select.dataset.items = signature;
    if (items.some(([value]) => value === prior)) select.value = prior;
  }
  window.renderKnowledge = status => {
    const catalog = status.knowledge_catalog || {tags: [], revision: ''};
    catalogRevision = catalog.revision;
    if (!learningDirty && status.experimental_learning) {
      for (const [key, value] of Object.entries(status.experimental_learning)) {
        const field = learningForm.elements.namedItem(key);
        if (field?.type === 'checkbox') field.checked = value;
        else if (field) field.value = value ?? '';
      }
    }
    document.querySelector('#experimental-models').textContent = (status.experimental_models || []).map(x => `${x.model} · ${x.effort} (pinned for ${x.evaluation})`).join(' · ');
    const STAGE = {queued: 'Waiting to sort', waiting_quota: 'Waiting for usage', running: 'Sorting', done: 'Sorted', completed: 'Sorted', failed: 'Could not sort'};
    document.querySelector("#knowledge-curations").textContent = (status.knowledge_curations || []).map(x => `${STAGE[x.stage] || x.stage.replaceAll('_', ' ')}: ${x.reason || x.assignment?.tags.join(", ") || "waiting for the adviser"}`).join(" · ");
    document.querySelector('#knowledge-catalog').textContent = catalog.tags.length ? 'Categories: ' + catalog.tags.map(t => `${t.label} (${t.id})`).join(' · ') : 'No categories yet. Add one below.';
    // Tick boxes instead of typing category names.
    for (const picker of document.querySelectorAll('.tag-picker')) {
      const input = picker.closest('form').elements.tags;
      const chosen = new Set(tags(input.value));
      const signature = JSON.stringify(catalog.tags.map(t => [t.id, t.label]));
      if (picker.dataset.items !== signature) {
        picker.replaceChildren(...catalog.tags.map(t => {
          const label = document.createElement('label');
          label.className = 'check';
          const box = document.createElement('input');
          box.type = 'checkbox'; box.dataset.tag = t.id; box.checked = chosen.has(t.id);
          box.onchange = () => { input.value = [...picker.querySelectorAll('input:checked')].map(b => b.dataset.tag).join(','); };
          label.append(box, document.createTextNode(t.label));
          return label;
        }));
        if (!catalog.tags.length) picker.textContent = 'No categories yet.';
        picker.dataset.items = signature;
      }
    }
    const material = (status.knowledge_assignments || []).map(row => {
      const source = (status.sources || []).find(s => s.id === row.item_id);
      const lesson = (status.lessons || []).find(s => s.id === row.item_id);
      return [JSON.stringify([row.kind, row.item_id]), `${row.kind}: ${source?.name || lesson?.asset_key || row.item_id} [${JSON.parse(row.tags).join(', ')}]`];
    });
    options(document.querySelector('#knowledge-item'), material);
    options(document.querySelector('#knowledge-task'), (status.tasks || []).filter(t => t.status === 'paused').map(t => [t.id, t.objective]));
    document.querySelector('#knowledge-scope-list').replaceChildren(...(status.knowledge_scopes || []).map(scope => {
      const p = document.createElement('p');
      const task = (status.tasks || []).find(t => t.id === scope.task_id);
      p.textContent = `${task?.objective || scope.task_id}: ${scope.selected ? scope.tags.join(', ') || 'no reference material' : 'not chosen yet'}`;
      return p;
    }));
  };
  function submit(id, path, payload) {
    document.querySelector(id).onsubmit = async event => {
      event.preventDefault();
      try { await api(path, payload(new FormData(event.target))); notice('Knowledge settings saved.'); await refresh(); }
      catch (error) { notice(error.message, true); }
    };
  }
  document.querySelector('#knowledge-curate').onclick = async () => {
    try {
      const [kind, id] = JSON.parse(document.querySelector('#knowledge-item').value);
      await api('knowledge/curate', {kind, id}); notice('The adviser will sort it shortly.'); await refresh();
    } catch (error) { notice(error.message, true); }
  };
  learningForm.onsubmit = async event => {
    event.preventDefault();
    const f = new FormData(learningForm);
    const value = {
      enabled: f.has('enabled'), chat_only: f.has('chat_only'),
      allow_unknown_allowance: f.has('allow_unknown_allowance'),
      share_captured_lessons: f.has('share_captured_lessons'),
      allow_native_benchmarks: f.has('allow_native_benchmarks'),
      route_override: f.get('route_override') || null,
      model_override: f.get('model_override').trim() || null,
      effort_override: f.get('effort_override').trim() || null,
      max_turns_per_evaluation: f.get('max_turns_per_evaluation') ? Number(f.get('max_turns_per_evaluation')) : null,
    };
    try { await api('learning/settings', value); learningDirty = false; notice('Learning settings saved.'); await refresh(); }
    catch (error) { notice(error.message, true); }
  };
  submit('#knowledge-tag-form'  , 'knowledge/tag', f => Object.fromEntries(f));
  submit('#knowledge-assignment-form', 'knowledge/assign', f => {
    const [kind, id] = JSON.parse(f.get('item'));
    if (!tags(f.get('tags')).length) throw new Error('Tick at least one category.');
    return {kind, id, tags: tags(f.get('tags'))};
  });
  // The short name follows the category name until it's edited by hand.
  const tagForm = document.querySelector('#knowledge-tag-form');
  let shortEdited = false;
  tagForm.elements.id.addEventListener('input', () => { shortEdited = true; });
  tagForm.elements.label.addEventListener('input', () => {
    if (!shortEdited) tagForm.elements.id.value = tagForm.elements.label.value.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
  });
  tagForm.addEventListener('submit', () => { shortEdited = false; });
  submit('#knowledge-scope-form', 'knowledge/scope', f => ({task: f.get('task'), tags: tags(f.get('tags')), catalog_revision: catalogRevision}));
})();
