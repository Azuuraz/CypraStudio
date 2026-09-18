const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/app.js', 'utf8');
function setup() {
  const track = {enabled:true};
  const lc = {active:true, muted:false, processing:false, state:'LISTENING', generation:1, stream:{getAudioTracks:()=>[track]}};
  let listens = 0;
  const ctx = vm.createContext({state:{liveCall:lc}, stopLocalRecorder(){}, stopBrowserRecognition(){}, setLiveCallState(next){lc.state=next;}, resumeLiveListening(){if(!lc.processing && !lc.muted) listens++;}});
  vm.runInContext(source.slice(source.indexOf('  function toggleLiveMute()'), source.indexOf('  async function prepareLocalSTTFromSettings')), ctx);
  return {lc, track, ctx, toggle:()=>vm.runInContext('toggleLiveMute()',ctx), listens:()=>listens};
}
test('mute disables audio and unmute resumes within same call', () => {
  const s=setup(); s.toggle(); assert.equal(s.track.enabled,false);
  s.toggle(); assert.equal(s.track.enabled,true); assert.equal(s.listens(),1); assert.equal(s.lc.generation,1);
});
test('mute during a response preserves processing state for automatic resume', () => {
  const s=setup(); s.lc.processing=true; s.lc.state='THINKING';
  s.toggle(); s.toggle();
  assert.equal(s.lc.state,'THINKING'); assert.equal(s.listens(),0);
});
test('unmute during preparation does not start recording early', () => {
  const s=setup(); s.lc.state='PREPARING'; s.toggle(); s.toggle();
  assert.equal(s.lc.state,'PREPARING'); assert.equal(s.listens(),0);
});
test('a transcript completed after mute and unmute is discarded', async () => {
  const s=setup(); let finish; let handled=0;
  s.ctx.FormData=class {append(){}};
  s.ctx.fetch=()=>new Promise(resolve=>{finish=resolve;});
  s.ctx.handleLiveTranscript=async()=>{handled++;};
  vm.runInContext(source.slice(source.indexOf('  async function transcribeLocalBlob'),source.indexOf('  function startLocalListening')),s.ctx);
  const pending=vm.runInContext("transcribeLocalBlob({size:100,type:'audio/webm'},1000)",s.ctx);
  s.toggle(); s.toggle(); finish({ok:true,json:async()=>({text:'stale audio'})}); await pending;
  assert.equal(handled,0);
});
