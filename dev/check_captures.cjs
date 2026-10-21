// Canvas data-path checks; this is a DOM fixture, not a real-browser claim.
const {JSDOM} = require('jsdom'), fs = require('fs'), assert = require('node:assert/strict');
const root = process.argv[2];
const dom = new JSDOM('<div id="target"></div>', {runScripts: 'outside-only'});
const w = dom.window;
const images = [], strokes = [];
const downloads = [], blobs = [];
w.URL.createObjectURL = blob => { blobs.push(blob); return 'blob:fixture'; };
w.URL.revokeObjectURL = () => {};
w.HTMLAnchorElement.prototype.click = function() { downloads.push({name:this.download,href:this.href}); };
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
images.length = 0;
const frames = {status:'completed', comparators:{scene:{format:'rgba8_sequence',width:1,height:1,frames:3,frame_rate_num:60,frame_rate_den:1}}, cases:[{
  id:'motion',passed:false,repeatable:true,
  expected:{file_contents_hex:{scene:'010203ff040506ff070809ff'}},
  runs:{candidate:[{file_contents_hex:{scene:'010203ff0a0b0cff070809ff'}}]},
  comparisons:{candidate:[{files:{scene:{first_failed_frame:1,frames:[{passed:true},{passed:false},{passed:true}]}}}]}
}]};
w.renderNativeCaptures(frames, target);
assert.deepEqual(images, [[1,2,3,255],[1,2,3,255]]);
const slider = target.querySelector('input[type=range]');
assert.equal(slider.max, '2');
[...target.querySelectorAll('button')].find(b => b.textContent === 'First failing frame').click();
assert.equal(slider.value, '1');
assert.deepEqual(images.slice(-2), [[4,5,6,255],[10,11,12,255]]);
assert.ok(target.textContent.includes('index 1 · declared time 0.016667 s'));
slider.value='2'; slider.dispatchEvent(new w.Event('input'));
assert.deepEqual(images.slice(-2), [[7,8,9,255],[7,8,9,255]]);
assert.ok([...target.querySelectorAll('canvas')].every(c => c.getAttribute('aria-label').includes('index 2')));
[...target.querySelectorAll('button')].find(b => b.textContent === 'Download candidate capture').click();
assert.deepEqual(downloads, [{name:'candidate-scene',href:'blob:fixture'}]);
assert.equal(blobs[0].size,12);
assert.equal(blobs[0].type,'application/octet-stream');
frames.cases[0].runs.candidate[0].file_contents_hex.scene = '00';
w.renderNativeCaptures(frames,target);
assert.equal(target.querySelectorAll('canvas').length,1);
assert.ok(target.textContent.includes('dimensions do not match'));
frames.comparators.scene.frames = 4097;
w.renderNativeCaptures(frames,target);
assert.equal(target.querySelectorAll('canvas,input').length,0);
assert.ok(target.textContent.includes('sequence dimensions or frame rate are invalid'));
w.renderNativeCaptures({status:'not_run'}, target);
assert.equal(target.querySelectorAll('canvas').length, 0);
assert.ok(target.textContent.includes('not_run'));
dom.window.close();
console.log('Capture view fixture passed: RGBA bytes, synchronized sequence scrubbing and failure jump, PCM channel waveform, missing captures, bounds and escaped labels');
