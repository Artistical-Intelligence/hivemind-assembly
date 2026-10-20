// Canvas data-path checks; this is a DOM fixture, not a real-browser claim.
const {JSDOM} = require('jsdom'), fs = require('fs'), assert = require('node:assert/strict');
const root = process.argv[2];
const dom = new JSDOM('<div id="target"></div>', {runScripts: 'outside-only'});
const w = dom.window;
const images = [], strokes = [];
w.HTMLCanvasElement.prototype.getContext = () => ({
  createImageData: (width, height) => ({data: new Uint8ClampedArray(width * height * 4)}),
  putImageData: data => images.push([...data.data]),
  beginPath: () => {}, moveTo: (x,y) => strokes.push([x,y]), lineTo: (x,y) => strokes.push([x,y]), stroke: () => {}
});
w.eval(fs.readFileSync(root + '/application/static/native_captures.js', 'utf8'));
const target = w.document.querySelector('#target');
const row = {file_contents_hex: {'<img src=x onerror=alert(1)>': '010203ff', 'tone': '0080ff7f00000000'}};
const result = {status: 'completed', comparators: {
  '<img src=x onerror=alert(1)>': {format:'rgba8', width:1, height:1},
  tone: {format:'pcm_s16le', channels:2, frames:2, sample_rate:8000}
}, cases:[{id:'<script>bad</script>', passed:true, repeatable:true, expected:row, runs:{candidate:[row]}}]};
w.renderNativeCaptures(result, target);
assert.equal(target.querySelectorAll('script,img').length, 0);
assert.deepEqual(images, [[1,2,3,255], [1,2,3,255]]);
target.querySelector('select').value = '1';
target.querySelector('select').dispatchEvent(new w.Event('change'));
assert.equal(target.querySelectorAll('canvas').length, 2);
assert.ok(strokes.length > 0 && strokes.every(pair => pair.every(Number.isFinite)));
assert.ok(target.textContent.includes('2 channels'));
result.cases[0].runs.candidate[0] = {file_contents_hex:{tone:'00'}};
w.renderNativeCaptures(result, target);
target.querySelector('select').value = '1';
target.querySelector('select').dispatchEvent(new w.Event('change'));
assert.ok(target.textContent.includes('sample count does not match'));
w.renderNativeCaptures({status:'not_run'}, target);
assert.equal(target.querySelectorAll('canvas').length, 0);
assert.ok(target.textContent.includes('not_run'));
dom.window.close();
console.log('Capture view fixture passed: RGBA bytes, PCM channel waveform, missing captures, bounds and escaped labels');
