'use strict';

// Owner-only observations view. All labels are text; captures never become HTML.
window.renderNativeCaptures = function(result, target) {
  target.replaceChildren();
  const cases = result.cases || [], rules = result.comparators || {};
  const program = ['windows_program','linux_program'].includes(result.scope);
  const paths = Object.keys(rules);
  const element = (tag, text, parent = target) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    parent.append(node);
    return node;
  };
  element('p', `${result.status || (program ? 'Emulated program observations' : 'No observations')} · ${cases.filter(c => c.passed).length} / ${cases.length} cases passed`);
  if (result.checked_revision !== undefined) element('p', `Checked revision ${result.checked_revision}${result.checked_revision !== result.current_revision ? ' · project has changed; rerun checks for current code.' : ''}`);
  if (!cases.length || !(program ? cases.some(c => Object.keys(c.captures || {}).length) : paths.length)) {
    element('p', 'No frame or audio captures are declared in this result.'); return;
  }
  const label = element('label', 'Capture');
  const select = element('select', undefined, label);
  const choices = [];
  for (const item of cases) for (const path of (program ? Object.keys(item.captures || {}) : paths)) {
    const index = choices.push({item, path, rule: program ? item.captures[path] : rules[path]}) - 1;
    const option = element('option', `${item.id} · ${path}`, select);
    option.value = index;
  }
  const pane = element('div');
  function show() {
    pane.replaceChildren();
    const {item, path, rule} = choices[Number(select.value) || 0];
    if (program) element('p', 'One bounded emulated replay per image with declared inputs. Native timing and repeatability are not measured.', pane);
    else element('p', item.repeatable ? 'Repeated captures were identical.' : 'Repeated captures differed; this case cannot pass.', pane);
    const metric = program ? item.capture_results?.[path] : item.comparisons?.candidate?.[0]?.files?.[path];
    const sequence = rule.format === 'rgba8_sequence';
    if (metric) {
      const {frames, ...summary} = metric;
      element('pre', JSON.stringify(sequence ? summary : metric, null, 2), pane);
    }
    const frameCount = sequence ? rule.frames : 1;
    const dimensionsValid = Number.isSafeInteger(rule.width) && Number.isSafeInteger(rule.height) && rule.width > 0 && rule.height > 0;
    const sequenceValid = Number.isSafeInteger(frameCount) && frameCount >= 1 && frameCount <= 4096 &&
      Number.isSafeInteger(rule.frame_rate_num) && rule.frame_rate_num > 0 && rule.frame_rate_num <= 1000000 &&
      Number.isSafeInteger(rule.frame_rate_den) && rule.frame_rate_den > 0 && rule.frame_rate_den <= 1000000;
    if (sequence && (!dimensionsValid || !sequenceValid || rule.width * rule.height * 4 * frameCount > 2097152)) {
      element('p', 'Capture sequence dimensions or frame rate are invalid.', pane); return;
    }
    const redraw = [];
    let slider, position, detail;
    function drawFrame() {
      const frame = slider ? Math.max(0, Math.min(frameCount - 1, Number(slider.value) || 0)) : 0;
      for (const draw of redraw) draw(frame);
      if (position) position.textContent = `Frame ${frame + 1} / ${frameCount} · index ${frame} · declared time ${(frame * rule.frame_rate_den / rule.frame_rate_num).toFixed(6)} s`;
      if (detail) detail.textContent = JSON.stringify(metric?.frames?.[frame] || {reason: 'Frame comparison unavailable'}, null, 2);
    }
    if (sequence) {
      const frameLabel = element('label', 'Frame (reference and candidate together)', pane);
      slider = element('input', undefined, frameLabel);
      slider.type = 'range'; slider.min = '0'; slider.max = String(frameCount - 1); slider.step = '1'; slider.value = '0';
      slider.oninput = drawFrame;
      position = element('p', undefined, pane);
      const failed = metric?.first_failed_frame;
      if (Number.isInteger(failed) && failed >= 0 && failed < frameCount) {
        const jump = element('button', 'First failing frame', pane);
        jump.type = 'button'; jump.onclick = () => { slider.value = String(failed); drawFrame(); };
      }
      element('p', 'Frames are compared at the same index. Times come from the declared frame rate; wall-clock timing is not measured.', pane);
      detail = element('pre', undefined, pane);
    }
    const reference = program ? item.original : item.expected || item.runs?.original?.[0];
    const candidate = program ? item.candidate : item.runs?.candidate?.[0];
    for (const [name, row] of [['Reference', reference], ['Candidate', candidate]]) {
      const hex = program ? (path === 'stdout' || path === 'stderr' ? row?.[path + '_hex'] : row?.files?.[path.slice(5)]) : row?.file_contents_hex?.[path];
      const panel = element('figure', undefined, pane);
      element('figcaption', `${name} · ${program ? 'emulated replay' : 'first repetition'}`, panel);
      if (typeof hex !== 'string' || hex.length > 4194304 || hex.length % 2 || !/^[0-9a-f]*$/i.test(hex)) {
        element('p', 'Capture unavailable or invalid.', panel); continue;
      }
      const bytes = Uint8Array.from(hex.match(/../g) || [], v => parseInt(v, 16));
      const download = element('button', `Download ${name.toLowerCase()} capture`, panel);
      download.type = 'button';
      download.onclick = () => {
        // The owner's explicit click exports the stored bytes, not a canvas
        // encoding (which could change alpha/color values). No capture is sent
        // to an external service or stored in a shareable URL.
        const url = URL.createObjectURL(new Blob([bytes], {type: 'application/octet-stream'}));
        const link = document.createElement('a');
        link.href = url;
        link.download = `${name.toLowerCase()}-${path.replace(/^file:/, '').split(/[\\/]/).pop() || 'capture.bin'}`;
        panel.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      if (rule.format === 'rgba8' || sequence) {
        if (!dimensionsValid || rule.width * rule.height * 4 * frameCount !== bytes.length) {
          element('p', 'Capture dimensions do not match.', panel); continue;
        }
        const canvas = element('canvas', undefined, panel);
        canvas.width = rule.width; canvas.height = rule.height;
        canvas.style.maxWidth = '100%'; canvas.style.imageRendering = 'pixelated';
        canvas.setAttribute('aria-label', `${name} RGBA capture in stored row order`);
        const context = canvas.getContext('2d');
        if (!context) { element('p', 'Canvas preview unavailable.', panel); continue; }
        const data = context.createImageData(rule.width, rule.height);
        const stride = rule.width * rule.height * 4;
        redraw.push(frame => {
          data.data.set(bytes.subarray(frame * stride, (frame + 1) * stride));
          context.putImageData(data, 0, 0);
          canvas.setAttribute('aria-label', `${name} RGBA capture in stored row order${sequence ? `, frame index ${frame}` : ''}`);
        });
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
    drawFrame();
  }
  select.onchange = show;
  show();
};
