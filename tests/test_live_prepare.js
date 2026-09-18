const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/app.js', 'utf8');
function context(api) {
  const ctx = vm.createContext({api, AbortController, DOMException, setTimeout, clearTimeout, Date, state:{settings:{}, liveCall:{active:true}}, setLiveCallState(){}, browserSpeechRecognitionCtor(){return null;}, refreshSTTStatus:async()=>{}});
  vm.runInContext(source.slice(source.indexOf('  function sttPrepareMessage'), source.indexOf('  async function startLiveCall')), ctx);
  return ctx;
}
test('cancelled preparation does not poll or update call state', async () => {
  let requests = 0;
  const ctx = context(async () => {requests++; return {local:{model_ready:true}};});
  const controller = new AbortController(); controller.abort();
  ctx.signal = controller.signal;
  await assert.rejects(vm.runInContext('pollLocalSTTPreparation({signal})', ctx), {name:'AbortError'});
  assert.equal(requests, 0);
});
test('ending a call cancels pending preparation requests', async () => {
  const ctx = context((path, opts) => new Promise((resolve, reject) => {
    opts?.signal?.addEventListener('abort', () => reject(opts.signal.reason), {once:true});
  }));
  const controller = new AbortController(); ctx.signal = controller.signal;
  const pending = vm.runInContext('prepareLiveCallSTT(signal)', ctx);
  controller.abort();
  await assert.rejects(pending, {name:'AbortError'});
});
test('unresponsive status request reports a timeout', async () => {
  const ctx = context((path, opts) => new Promise((resolve, reject) => {
    opts.signal.addEventListener('abort', () => reject(opts.signal.reason), {once:true});
  }));
  ctx.setTimeout = callback => {queueMicrotask(callback); return 0;};
  await assert.rejects(vm.runInContext("sttRequest('/api/stt/status')", ctx), /request timed out/);
});
