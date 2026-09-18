const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/app.js', 'utf8');
test('Edge segment failures do not silently switch to browser voice', async () => {
  const ctx = vm.createContext({fetch:async()=>({ok:false,status:503,json:async()=>({detail:{error:'browser_tts',message:'fallback'}})}), AbortController, state:{ttsAbort:null}});
  vm.runInContext(source.slice(source.indexOf('  async function fetchServerSpeechBlob'), source.indexOf('  async function playVoiceBlob')), ctx);
  await assert.rejects(vm.runInContext("fetchServerSpeechBlob('segment', {configured:'edge', voiceId:'x', expression:{}, allowBrowserFallback:false})", ctx), /fallback/);
});
