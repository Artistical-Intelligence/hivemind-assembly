'use strict';
(() => {
  let catalogRevision = '';
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
    document.querySelector("#knowledge-curations").textContent = (status.knowledge_curations || []).map(x => `${x.stage}: ${x.reason || x.assignment?.tags.join(", ") || "categorization queued"}`).join(" · ");
    document.querySelector('#knowledge-catalog').textContent = catalog.tags.map(t => `${t.id}: ${t.label}`).join(' · ') || 'No categories yet.';
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
      p.textContent = `${task?.objective || scope.task_id}: ${scope.selected ? scope.tags.join(', ') || 'No matching knowledge selected' : 'Awaiting task classification'}`;
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
      await api('knowledge/curate', {kind, id}); notice('Automatic categorization queued.'); await refresh();
    } catch (error) { notice(error.message, true); }
  };
  submit('#knowledge-tag-form' , 'knowledge/tag', f => Object.fromEntries(f));
  submit('#knowledge-assignment-form', 'knowledge/assign', f => {
    const [kind, id] = JSON.parse(f.get('item')); return {kind, id, tags: tags(f.get('tags'))};
  });
  submit('#knowledge-scope-form', 'knowledge/scope', f => ({task: f.get('task'), tags: tags(f.get('tags')), catalog_revision: catalogRevision}));
})();
