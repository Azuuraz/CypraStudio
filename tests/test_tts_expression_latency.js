const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/js/app.js', 'utf8');
const start = source.indexOf('  function edgeNeedsSpeechPlan');
const end = source.indexOf('  function waitSpeechPause', start);
const helperSource = source.slice(start, end);

test('short ordinary Edge speech avoids planner round trip', () => {
  const ctx = vm.createContext({});
  vm.runInContext(helperSource, ctx);
  assert.equal(vm.runInContext("edgeNeedsSpeechPlan('Hello — are you ready?')", ctx), false);
  assert.equal(vm.runInContext("edgeNeedsSpeechPlan('Great news!')", ctx), false);
});

test('explicit expression/pause cues use local planner', () => {
  const ctx = vm.createContext({});
  vm.runInContext(helperSource, ctx);
  assert.equal(vm.runInContext("edgeNeedsSpeechPlan('[soft] Keep this gentle.')", ctx), true);
  assert.equal(vm.runInContext("edgeNeedsSpeechPlan('Wait. [pause:450] Continue.')", ctx), true);
  assert.equal(vm.runInContext("edgeNeedsSpeechPlan('[emphasis] Important.')", ctx), true);
});
