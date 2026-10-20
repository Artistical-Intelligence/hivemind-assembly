'use strict';

// Owner-only observations view. All labels are text; captures never become HTML.
window.renderNativeCaptures = function(result, target) {
  target.replaceChildren();
  const cases = result.cases || [], rules = result.comparators || {};
  const paths = Object.keys(rules);
  const element = (tag, text, parent = target) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    parent.append(node);
    return node;
  };
  element('p', `${result.status || 'No observations'} · ${cases.filter(c => c.passed).length} / ${cases.length} cases passed`);
  if (!paths.length || !cases.length) return;
  const label = element('label', 'Capture');
  const select = element('select', undefined, label);
  const choices = [];
  for (const item of cases) for (const path of paths) {
    const index = choices.push({item, path, rule: rules[path]}) - 1;
    const option = element('option', `${item.id} · ${path}`, select);
    option.value = index;
  }
  const pane = element('div');
  function show() {
    pane.replaceChildren();
    const {item, path, rule} = choices[Number(select.value) || 0];
    element('p', item.repeatable ? 'Repeated captures were identical.' : 'Repeated captures differed; this case cannot pass.', pane);
    const metric = item.comparisons?.candidate?.[0]?.files?.[path];
    if (metric) element('pre', JSON.stringify(metric, null, 2), pane);
    const reference = item.expected || item.runs?.original?.[0];
    for (const [name, row] of [['Reference', reference], ['Candidate', item.runs?.candidate?.[0]]]) {
      const hex = row?.file_contents_hex?.[path];
      const panel = element('figure', undefined, pane);
      element('figcaption', `${name} · first repetition`, panel);
      if (typeof hex !== 'string' || hex.length > 4194304 || hex.length % 2 || !/^[0-9a-f]*$/i.test(hex)) {
        element('p', 'Capture unavailable or invalid.', panel); continue;
      }
      const bytes = Uint8Array.from(hex.match(/../g) || [], v => parseInt(v, 16));
      if (rule.format === 'rgba8') {
        if (!Number.isSafeInteger(rule.width) || !Number.isSafeInteger(rule.height) || rule.width < 1 || rule.height < 1 || rule.width * rule.height * 4 !== bytes.length) {
          element('p', 'Capture dimensions do not match.', panel); continue;
        }
        const canvas = element('canvas', undefined, panel);
        canvas.width = rule.width; canvas.height = rule.height;
        canvas.style.maxWidth = '100%'; canvas.style.imageRendering = 'pixelated';
        canvas.setAttribute('aria-label', `${name} RGBA capture in stored row order`);
        const context = canvas.getContext('2d');
        if (!context) { element('p', 'Canvas preview unavailable.', panel); continue; }
        const data = context.createImageData(rule.width, rule.height);
        data.data.set(bytes); context.putImageData(data, 0, 0);
      } else if (rule.format === 'pcm_s16le') {
        if (!Number.isSafeInteger(rule.channels) || rule.channels < 1 || rule.channels > 32 || bytes.length !== rule.frames * rule.channels * 2) {
          element('p', 'Capture sample count does not match.', panel); continue;
        }
        // Waveform preview uses all samples in each pixel bucket, so peaks survive.
        const canvas = element('canvas', undefined, panel);
        canvas.width = 640; canvas.height = Math.min(512, 64 * rule.channels);
        canvas.style.maxWidth = '100%';
        canvas.setAttribute('aria-label', `${name} audio waveform by channel`);
        const context = canvas.getContext('2d');
        if (!context) { element('p', 'Canvas preview unavailable.', panel); continue; }
        const view = new DataView(bytes.buffer);
        const lane = canvas.height / rule.channels;
        context.strokeStyle = '#4da6ff';
        for (let c = 0; c < rule.channels; c++) {
          const middle = (c + 0.5) * lane;
          context.beginPath();
          for (let x = 0; x < 640; x++) {
            const start = Math.floor(x * rule.frames / 640), end = Math.min(rule.frames, Math.max(start + 1, Math.floor((x + 1) * rule.frames / 640)));
            let low = 32767, high = -32768;
            for (let i = start; i < end; i++) { const value = view.getInt16((i * rule.channels + c) * 2, true); low = Math.min(low, value); high = Math.max(high, value); }
            context.moveTo(x, middle - high / 32768 * lane * 0.45);
            context.lineTo(x, middle - low / 32768 * lane * 0.45);
          }
          context.stroke();
        }
        element('p', `${rule.channels} channels · ${rule.sample_rate} Hz · ${rule.frames} frames`, panel);
      }
    }
  }
  select.onchange = show;
  show();
};
