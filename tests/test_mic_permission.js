const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/app.js', 'utf8');
function load(confirm, getUserMedia) {
  const ctx = vm.createContext({confirm, navigator:{mediaDevices:{getUserMedia}}});
  const start = source.indexOf('  async function requestLiveMicrophonePermission(');
  assert.notEqual(start, -1, 'microphone consent function exists');
  vm.runInContext(source.slice(start, source.indexOf('  async function startLiveCall', start)), ctx);
  return () => vm.runInContext('requestLiveMicrophonePermission()', ctx);
}
test('Cancel does not access microphone', async () => {
  const request = load(() => false, () => {throw Error('must not capture');});
  assert.equal(await request(), false);
});
test('Allow requests audio only and releases permission-check capture', async () => {
  let stopped = false;
  const request = load(() => true, async opts => {
    assert.equal(opts.audio, true); assert.equal(opts.video, false);
    return {getTracks:() => [{stop(){stopped = true;}}]};
  });
  assert.equal(await request(), true);
  assert.equal(stopped, true);
});
test('blocked microphone gives actionable feedback', async () => {
  const request = load(() => true, async () => {throw {name:'NotAllowedError'};});
  await assert.rejects(request(), /Microphone access was denied/);
});
