(() => {
  const $ = (q) => document.querySelector(q);
  const $$ = (q) => [...document.querySelectorAll(q)];
  const state = {
    settings: {}, runtime: {}, sessions: [], session: null, uiState: {},
    abort: null, dirty: false, pullTimer: null, runtimeWatchTimer: null, search: '', uiStateTimer: null, sessionViewTimer: null, settingsSaveTimer: null, settingsSaveSeq: 0, lastRenderedSessionId: '', lastChatSessionId: '', commandIndex: 0, sessionMenu: null, toastTimer: null,
    specialistGroups: [], specialistAgents: [], specialistGroup: '', selectedSpecialist: null, generationPhase: 'ready', controlMenu: null, heroExitActive: false,
    hfRepo: null, hfGroups: [], hfSelectedGroup: '', hfPollTimer: null, shutdownActive: false,
    ttsAbort: null, ttsAudio: null, ttsAudioUrl: '', ttsToken: 0, ttsPlaying: false, edgeVoicesLoaded: false, edgeVoicesLoading: false,
    liveCall: {active:false, muted:false, state:'IDLE', mode:'local', stream:null, audioContext:null, analyser:null, source:null, vadTimer:null, recorder:null, chunks:[], recorderDiscard:false, speechHeard:false, lastVoiceAt:0, recordingStartedAt:0, browserRecognition:null, browserRestartTimer:null, processing:false, generation:0, speakerStartedAt:0, bargeFrames:0}
  };

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (!r.ok) {
      let detail = `${r.status} ${r.statusText}`;
      try { const j = await r.json(); detail = j.detail || detail; } catch {}
      const err = new Error(detail); err.status = r.status; throw err;
    }
    return r.json();
  }

  const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
  const COMPACT_LAYOUT_WIDTH = 1040;
  const TTS_HARD_CEILING = 50000;

  let backgroundResizeTimer = 0;
  const backgroundAsset = {url:'', width:0, height:0, token:0};

  function clearBackgroundEdges() {
    $$('.workspace-bg-edge').forEach(el => {
      el.style.width = '0px'; el.style.height = '0px';
      el.style.top = ''; el.style.right = ''; el.style.bottom = ''; el.style.left = '';
    });
  }

  function layoutBackgroundEdges() {
    const host = $('.workspace-background');
    if (!host || !document.body.classList.contains('background-image-active') || !backgroundAsset.width || !backgroundAsset.height) {
      clearBackgroundEdges(); return;
    }
    const rect = host.getBoundingClientRect();
    const w = Math.max(1, rect.width), h = Math.max(1, rect.height);
    const scale = Math.min(w / backgroundAsset.width, h / backgroundAsset.height);
    const shownW = backgroundAsset.width * scale, shownH = backgroundAsset.height * scale;
    const gapX = Math.max(0, (w - shownW) / 2);
    const gapY = Math.max(0, (h - shownH) / 2);
    // Extend the edge fill slightly beneath the sharp artwork. CSS masks that
    // overlap back to transparent, replacing the old hard letterbox seam with
    // a short soft handoff. The foreground image itself stays untouched.
    const fadeOverlap = 26;
    const top = $('.edge-top'), right = $('.edge-right'), bottom = $('.edge-bottom'), left = $('.edge-left');
    if (top) { top.style.cssText = `top:0;left:0;width:100%;height:${gapY > .5 ? gapY + fadeOverlap : 0}px`; }
    if (bottom) { bottom.style.cssText = `bottom:0;left:0;width:100%;height:${gapY > .5 ? gapY + fadeOverlap : 0}px`; }
    if (left) { left.style.cssText = `top:0;left:0;height:100%;width:${gapX > .5 ? gapX + fadeOverlap : 0}px`; }
    if (right) { right.style.cssText = `top:0;right:0;height:100%;width:${gapX > .5 ? gapX + fadeOverlap : 0}px`; }
  }

  function loadBackgroundMetrics(url) {
    const token = ++backgroundAsset.token;
    backgroundAsset.url = url || ''; backgroundAsset.width = 0; backgroundAsset.height = 0;
    if (!url) { clearBackgroundEdges(); return; }
    const img = new Image();
    img.onload = () => {
      if (token !== backgroundAsset.token) return;
      backgroundAsset.width = img.naturalWidth || 0; backgroundAsset.height = img.naturalHeight || 0;
      requestAnimationFrame(layoutBackgroundEdges);
    };
    img.onerror = () => { if (token === backgroundAsset.token) clearBackgroundEdges(); };
    img.src = url;
  }

  function sidebarCollapsedSnapshot() {
    return document.body.classList.contains('sidebar-collapsed');
  }

  function revealSidebar() {
    document.body.classList.remove('sidebar-collapsed');
    persistUiState({sidebar_collapsed:false});
  }

  function syncResponsiveShell() {
    const compact = innerWidth <= COMPACT_LAYOUT_WIDTH;
    document.body.classList.toggle('compact-layout', compact);
    document.body.classList.remove('sidebar-open');
    document.body.classList.toggle('sidebar-collapsed', !!state.uiState?.sidebar_collapsed);
  }

  window.addEventListener('resize', () => {
    clearTimeout(backgroundResizeTimer);
    backgroundResizeTimer = setTimeout(() => requestAnimationFrame(layoutBackgroundEdges), 40);
    syncResponsiveShell();
    positionControlMenu();
    if (innerWidth >= 900 && innerHeight >= 650) persistUiState({window_width:Math.round(innerWidth), window_height:Math.round(innerHeight)}, 500);
  }, {passive:true});

  function beaconJson(path, payload) {
    try {
      return navigator.sendBeacon(path, new Blob([JSON.stringify(payload)], {type:'application/json'}));
    } catch { return false; }
  }

  window.addEventListener('pagehide', () => {
    const snapshot = sessionViewSnapshot();
    beaconJson('/api/ui-state', {...snapshot, sidebar_collapsed:sidebarCollapsedSnapshot()});
    try { beaconJson('/api/settings', collectSettings()); } catch {}
    stopSpeech({notifyBackend:false, release:true});
  });

  document.addEventListener('visibilitychange', () => {
    const hidden = document.visibilityState === 'hidden';
    document.body.classList.toggle('window-inactive', hidden);
    if (!hidden || !state.dirty) return;
    try { beaconJson('/api/settings', collectSettings()); } catch {}
  });
  window.addEventListener('blur', () => {
    if (!state.dirty) return;
    void flushSettingsAutosave();
  });
  const boolValue = (v) => typeof v === 'string' ? ['1','true','yes','on'].includes(v.trim().toLowerCase()) : !!v;



  function syncVoiceStopButton() {
    const button = $('#stop-voice-main');
    if (!button) return;
    button.hidden = !(state.ttsPlaying || state.ttsAbort || state.liveCall?.state === 'SPEAKING');
  }

  function sanitizeBrowserSpeech(text) {
    let value = String(text || '');
    if (state.settings.tts_skip_code !== false) value = value.replace(/```[\s\S]*?```|~~~[\s\S]*?~~~/g, ' Code block omitted. ');
    if (state.settings.tts_skip_urls !== false) value = value.replace(/https?:\/\/\S+|www\.\S+/gi, ' ');
    value = value
      .replace(/^\s*(?:tokens?|prompt tokens?|completion tokens?|elapsed|latency|speed|model|provider)\s*:\s*.*$/gim, ' ')
      .replace(/\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]/g, (_, title, display) => display || title)
      .replace(/[#*_`>]+/g, ' ')
      .replace(/\s*\n+\s*/g, ' ... ')
      .replace(/\.{4,}/g, '...')
      .replace(/[ \t]+/g, ' ')
      .trim();
    const rawMaximum = Number(state.settings.tts_max_chars);
    const maximum = Number.isFinite(rawMaximum) ? clamp(rawMaximum, 100, TTS_HARD_CEILING) : TTS_HARD_CEILING;
    if (value.length <= maximum) return value;
    const clipped = value.slice(0, maximum).trimEnd();
    const boundary = Math.max(clipped.lastIndexOf('. '), clipped.lastIndexOf('! '), clipped.lastIndexOf('? '));
    return (boundary > Math.floor(maximum * .45) ? clipped.slice(0, boundary + 1) : clipped.replace(/\s+\S*$/, '')).trim();
  }

  function stopSpeech({notifyBackend=true, release=false} = {}) {
    state.ttsToken += 1;
    state.ttsPlaying = false;
    if (state.ttsAbort) { try { state.ttsAbort.abort(); } catch {} state.ttsAbort = null; }
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch {}
    if (state.ttsAudio) {
      try { state.ttsAudio.pause(); state.ttsAudio.src = ''; } catch {}
      state.ttsAudio = null;
    }
    if (state.ttsAudioUrl) { try { URL.revokeObjectURL(state.ttsAudioUrl); } catch {} state.ttsAudioUrl = ''; }
    if ($('#tts-status')) $('#tts-status').textContent = state.settings.voice_output_enabled ? 'Voice ready' : 'Voice output is off';
    syncVoiceStopButton();
    if (notifyBackend) {
      fetch('/api/tts/stop', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({release:!!release})}).catch(()=>{});
    }
  }

  function speakBrowser(text, token = state.ttsToken) {
    return new Promise((resolve, reject) => {
      const clean = sanitizeBrowserSpeech(text);
      if (!clean) { resolve(); return; }
      if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === 'undefined') { reject(new Error('Device speech synthesis is unavailable')); return; }
      const utter = new SpeechSynthesisUtterance(clean);
      const expression = currentTTSExpressionSettings();
      utter.rate = expression.rate;
      utter.pitch = expression.pitch;
      utter.volume = clamp(expression.volume, 0, 1);
      try {
        const voices = speechSynthesis.getVoices() || [];
        const preferred = voices.find(v => /en(-|_)US/i.test(v.lang) && /natural|neural|premium/i.test(v.name)) || voices.find(v => /^en/i.test(v.lang)) || voices[0];
        if (preferred) utter.voice = preferred;
      } catch {}
      utter.onend = () => { if (token === state.ttsToken) state.ttsPlaying = false; if ($('#tts-status')) $('#tts-status').textContent = 'Voice ready'; resolve(); };
      utter.onerror = event => { if (token === state.ttsToken) state.ttsPlaying = false; reject(new Error(event?.error || 'Device speech failed')); };
      state.ttsPlaying = true; syncVoiceStopButton();
      if ($('#tts-status')) $('#tts-status').textContent = 'Speaking with device voice…';
      speechSynthesis.cancel();
      speechSynthesis.speak(utter);
    });
  }

  function currentTTSExpressionSettings() {
    const rate = Number($('#set-tts-rate')?.value ?? state.settings.tts_rate ?? 1);
    const pitch = Number($('#set-tts-pitch')?.value ?? state.settings.tts_pitch ?? 1);
    const volume = Number($('#set-tts-volume')?.value ?? state.settings.tts_volume ?? 1);
    const intensity = Number($('#set-tts-intensity')?.value ?? state.settings.tts_intensity ?? .7);
    return {
      rate: clamp(Number.isFinite(rate) ? rate : 1, .5, 2),
      pitch: clamp(Number.isFinite(pitch) ? pitch : 1, .5, 2),
      volume: clamp(Number.isFinite(volume) ? volume : 1, .5, 1.5),
      tone: String($('#set-tts-tone')?.value || state.settings.tts_tone || 'neutral'),
      intensity: clamp(Number.isFinite(intensity) ? intensity : .7, 0, 1),
      pause_style: String($('#set-tts-pause-style')?.value || state.settings.tts_pause_style || 'natural')
    };
  }

  function waitSpeechPause(ms, token) {
    const delay = clamp(Number(ms) || 0, 0, 2000);
    if (!delay || token !== state.ttsToken) return Promise.resolve();
    return new Promise(resolve => {
      const deadline = performance.now() + delay;
      const tick = () => {
        if (token !== state.ttsToken || performance.now() >= deadline) { resolve(); return; }
        setTimeout(tick, Math.min(50, Math.max(10, deadline - performance.now())));
      };
      tick();
    });
  }

  async function fetchServerSpeechBlob(text, {configured, voiceId, expression, preview=false}) {
    const controller = new AbortController();
    state.ttsAbort = controller;
    try {
      const response = await fetch('/api/tts', {
        method:'POST', headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({
          text, voice_id:voiceId, provider:configured, replace:false, preview:!!preview,
          rate:expression.rate, pitch:expression.pitch, volume:expression.volume,
          tone:expression.tone, intensity:expression.intensity
        })
      });
      if (!response.ok) {
        let payload = {}; try { payload = await response.json(); } catch {}
        const detail = payload?.detail;
        if (detail?.error === 'browser_tts') return {browserFallback:true, text};
        const message = typeof detail === 'string' ? detail : (detail?.message || `Voice synthesis failed (${response.status})`);
        throw new Error(message);
      }
      return {blob:await response.blob(), text};
    } finally {
      if (state.ttsAbort === controller) state.ttsAbort = null;
    }
  }

  function prefetchEdgeSegment(text, options) {
    // Resolve failures into a value while current audio is playing. That avoids
    // an unhandled-rejection race if the prefetched request fails early; the
    // main playback loop raises the error when it reaches that chunk.
    return fetchServerSpeechBlob(text, {...options, configured:'edge'}).then(
      result => ({result}),
      error => ({error})
    );
  }

  async function playVoiceBlob(blob, token, providerLabel) {
    if (token !== state.ttsToken || !blob) return false;
    if (state.ttsAudioUrl) { try { URL.revokeObjectURL(state.ttsAudioUrl); } catch {} state.ttsAudioUrl = ''; }
    const url = URL.createObjectURL(blob); state.ttsAudioUrl = url;
    const audio = new Audio(url); state.ttsAudio = audio; state.ttsPlaying = true; syncVoiceStopButton();
    if ($('#tts-status')) $('#tts-status').textContent = `Speaking with ${providerLabel}…`;
    await new Promise((resolve, reject) => {
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error('Voice audio playback failed'));
      audio.play().catch(reject);
    });
    if (state.ttsAudio === audio) state.ttsAudio = null;
    if (state.ttsAudioUrl === url) { URL.revokeObjectURL(url); state.ttsAudioUrl = ''; }
    return token === state.ttsToken;
  }

  async function requestServerSpeech(text, {configured, voiceId, expression, token, preview=false}) {
    const prepared = await fetchServerSpeechBlob(text, {configured, voiceId, expression, preview});
    if (prepared?.browserFallback) return prepared;
    const played = await playVoiceBlob(prepared.blob, token, configured === 'edge' ? 'Edge' : 'Piper');
    return {played};
  }

  async function speakText(text, {preview=false, provider=null, button=null} = {}) {
    const configured = String(provider || state.settings.tts_provider || 'browser').toLowerCase();
    if (!preview && !state.settings.voice_output_enabled) throw new Error('Voice Output is disabled');
    if (configured === 'off') throw new Error('Voice provider is Off');
    const clean = sanitizeBrowserSpeech(text);
    if (!clean) return;

    if (state.settings.tts_stop_previous !== false) {
      stopSpeech({notifyBackend:false});
      if (configured !== 'browser') {
        try { await fetch('/api/tts/stop', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({release:false})}); } catch {}
      }
    }
    const token = ++state.ttsToken;
    state.ttsPlaying = true; syncVoiceStopButton();
    const originalLabel = button?.textContent || '';
    if (button) { button.disabled = true; button.textContent = 'VOICE…'; }
    try {
      if (configured === 'browser') { await speakBrowser(clean, token); return; }
      const expression = currentTTSExpressionSettings();
      const voiceId = configured === 'edge' ? (state.settings.tts_edge_voice || $('#set-tts-edge-voice')?.value || 'en-US-AvaNeural') : (state.settings.tts_local_voice || 'en_US-lessac-medium');

      if (configured === 'edge') {
        if ($('#tts-status')) $('#tts-status').textContent = 'Planning expressive Edge speech…';
        state.ttsAbort = new AbortController();
        const planResponse = await fetch('/api/tts/plan', {
          method:'POST', headers:{'Content-Type':'application/json'}, signal:state.ttsAbort.signal,
          body:JSON.stringify({text:String(text || ''), tone:expression.tone, intensity:expression.intensity, pause_style:expression.pause_style})
        });
        state.ttsAbort = null;
        if (!planResponse.ok) {
          let payload = {}; try { payload = await planResponse.json(); } catch {}
          const detail = payload?.detail;
          throw new Error(typeof detail === 'string' ? detail : (detail?.message || `Edge speech planning failed (${planResponse.status})`));
        }
        const plan = await planResponse.json();
        if (!Array.isArray(plan?.segments) || !plan.segments.length) throw new Error('Edge speech plan returned no speakable segments');
        expression.tone = String(plan.tone || expression.tone);
        expression.intensity = clamp(Number(plan.intensity ?? expression.intensity), 0, 1);
        if ($('#tts-status')) $('#tts-status').textContent = `Edge · ${expression.tone.toUpperCase()} · ${plan.segments.length} segment${plan.segments.length === 1 ? '' : 's'}`;
        const speechSegments = plan.segments
          .map(segment => ({...segment, text:String(segment?.text || '').trim()}))
          .filter(segment => !!segment.text);
        if (!speechSegments.length) throw new Error('Edge speech plan returned no speakable segments');

        let pendingSpeech = prefetchEdgeSegment(speechSegments[0].text, {voiceId, expression, preview});
        for (let index = 0; index < speechSegments.length; index += 1) {
          if (token !== state.ttsToken) return;
          const segment = speechSegments[index];
          const prefetched = await pendingSpeech;
          if (prefetched?.error) throw prefetched.error;
          const preparedSpeech = prefetched?.result;
          if (token !== state.ttsToken) return;

          // Start synthesis of the next long-form chunk before current audio
          // begins playing. This hides most Edge network/synthesis latency.
          pendingSpeech = index + 1 < speechSegments.length
            ? prefetchEdgeSegment(speechSegments[index + 1].text, {voiceId, expression, preview})
            : null;

          if (preparedSpeech?.browserFallback) await speakBrowser(segment.text, token);
          else await playVoiceBlob(preparedSpeech?.blob, token, 'Edge');
          if (token !== state.ttsToken) return;
          await waitSpeechPause(segment.pause_after_ms, token);
        }
      } else {
        if ($('#tts-status')) $('#tts-status').textContent = 'Preparing local Piper speech…';
        const result = await requestServerSpeech(clean, {configured, voiceId, expression, token, preview});
        if (result?.browserFallback) await speakBrowser(clean, token);
      }

      if (token === state.ttsToken) {
        state.ttsPlaying = false;
        if ($('#tts-status')) $('#tts-status').textContent = 'Voice ready';
      }
    } catch (error) {
      if (error?.name === 'AbortError') return;
      if ($('#tts-status')) $('#tts-status').textContent = error.message || 'Voice failed';
      throw error;
    } finally {
      state.ttsAbort = null;
      if (token === state.ttsToken) state.ttsPlaying = false;
      syncVoiceStopButton();
      if (button) { button.disabled = false; button.textContent = originalLabel || 'SPEAK'; }
    }
  }

  async function refreshTTSStatus() {
    const el = $('#tts-status');
    if (!el) return;
    try {
      const status = await api('/api/tts/status');
      if (!status.voice_output_enabled) el.textContent = 'Voice output is off';
      else if (status.configured === 'edge' && !status.allow_online) el.textContent = 'Edge blocked by privacy gate · browser fallback available';
      else if (status.configured === 'edge' && status.allow_online && !status.local?.edge_dependency) el.textContent = 'Edge support will self-prepare when voices or speech are requested';
      else if (status.configured === 'local' && !(status.local?.ready && status.local?.dependency)) el.textContent = 'Piper unavailable · install local voice assets/dependency or use browser';
      else el.textContent = `${String(status.configured || 'browser').toUpperCase()} voice ready`;
    } catch { el.textContent = 'Voice status unavailable'; }
  }

  async function refreshSTTStatus() {
    const el = $('#stt-status');
    if (!el) return null;
    try {
      const status = await api('/api/stt/status');
      const local = status.local || {};
      const phase = String(local.prepare_state || '').toLowerCase();
      if (local.model_ready) el.textContent = `Local STT ready · ${status.local_model || local.model || 'base.en'} · CPU int8`;
      else if (['queued','installing','downloading','loading'].includes(phase)) el.textContent = sttPrepareMessage(local);
      else if (phase === 'error') el.textContent = `${local.last_error || local.prepare_message || 'Local STT preparation failed'} · see MatrixFiles/Voice/STT/prepare.log`;
      else if (local.dependency) el.textContent = `Local STT dependency ready · prepare ${status.local_model || 'base.en'} model`;
      else el.textContent = 'Local STT not prepared · Live Call can prepare it on demand';
      return status;
    } catch {
      el.textContent = 'Local STT status unavailable';
      return null;
    }
  }

  function browserSpeechRecognitionCtor() {
    return window.SpeechRecognition || window.webkitSpeechRecognition || null;
  }

  function setLiveCallState(next, detail='') {
    const lc = state.liveCall;
    lc.state = String(next || 'IDLE').toUpperCase();
    const label = $('#live-call-state');
    if (label) {
      label.hidden = !lc.active;
      label.textContent = lc.active ? `LIVE · ${lc.muted ? 'MIC MUTED' : lc.state}${detail ? ` · ${detail}` : ''}` : 'LIVE · IDLE';
    }
    const main = $('#live-call');
    if (main) main.textContent = lc.active ? 'END CALL' : 'LIVE CALL';
    const mute = $('#live-call-mute');
    if (mute) { mute.hidden = !lc.active; mute.textContent = lc.muted ? 'UNMUTE MIC' : 'MUTE MIC'; }
    syncVoiceStopButton();
  }

  function stopBrowserRecognition() {
    const lc = state.liveCall;
    clearTimeout(lc.browserRestartTimer); lc.browserRestartTimer = null;
    if (lc.browserRecognition) {
      try { lc.browserRecognition.onend = null; lc.browserRecognition.abort(); } catch {}
      lc.browserRecognition = null;
    }
  }

  function stopLocalRecorder({discard=true} = {}) {
    const lc = state.liveCall;
    const recorder = lc.recorder;
    if (!recorder) return;
    lc.recorderDiscard = !!discard;
    if (recorder.state !== 'inactive') { try { recorder.stop(); } catch {} }
  }

  function liveAudioLevel() {
    const analyser = state.liveCall.analyser;
    if (!analyser) return 0;
    const buffer = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(buffer);
    let sum = 0;
    for (const value of buffer) { const normalized = (value - 128) / 128; sum += normalized * normalized; }
    return Math.sqrt(sum / Math.max(1, buffer.length));
  }

  function startLiveVadLoop() {
    const lc = state.liveCall;
    if (lc.vadTimer) return;
    lc.vadTimer = setInterval(() => {
      if (!lc.active || lc.muted || !lc.analyser) return;
      const now = performance.now();
      const level = liveAudioLevel();
      if (lc.state === 'LISTENING' && lc.mode === 'local' && lc.recorder) {
        if (level >= 0.030) { lc.speechHeard = true; lc.lastVoiceAt = now; }
        if (lc.speechHeard && now - lc.lastVoiceAt >= 950) {
          setLiveCallState('TRANSCRIBING');
          stopLocalRecorder({discard:false});
        } else if (!lc.speechHeard && now - lc.recordingStartedAt >= 15000) {
          stopLocalRecorder({discard:true});
        } else if (now - lc.recordingStartedAt >= 60000) {
          setLiveCallState(lc.speechHeard ? 'TRANSCRIBING' : 'LISTENING');
          stopLocalRecorder({discard:!lc.speechHeard});
        }
      } else if (lc.state === 'SPEAKING' && lc.mode === 'local' && now - lc.speakerStartedAt > 650) {
        if (level >= 0.075) lc.bargeFrames += 1; else lc.bargeFrames = 0;
        if (lc.bargeFrames >= 3) {
          lc.bargeFrames = 0; lc.processing = false;
          stopSpeech({notifyBackend:true, release:false});
          setLiveCallState('LISTENING', 'interrupted');
          setTimeout(() => { if (lc.active && !lc.processing) startLocalListening(); }, 40);
        }
      }
    }, 80);
  }

  async function ensureLocalMicStream() {
    const lc = state.liveCall;
    const generation = lc.generation;
    if (lc.stream?.active && lc.analyser) return lc.stream;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone capture is unavailable in this WebView');
    const stream = await navigator.mediaDevices.getUserMedia({
      audio:{echoCancellation:true, noiseSuppression:true, autoGainControl:true, channelCount:1},
      video:false
    });
    if (!lc.active || lc.generation !== generation) { stream.getTracks().forEach(track => track.stop()); return null; }
    stream.getAudioTracks().forEach(track => { track.enabled = !lc.muted; });
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) { stream.getTracks().forEach(track => track.stop()); throw new Error('Web Audio is unavailable'); }
    const audioContext = new AudioContextCtor();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.2;
    source.connect(analyser);
    lc.stream = stream; lc.audioContext = audioContext; lc.source = source; lc.analyser = analyser;
    startLiveVadLoop();
    return stream;
  }

  function recorderMimeType() {
    if (typeof MediaRecorder === 'undefined') return '';
    for (const type of ['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus','audio/ogg']) {
      if (!MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(type)) return type;
    }
    return '';
  }

  async function transcribeLocalBlob(blob, durationMs) {
    const lc = state.liveCall;
    if (lc.muted) return;
    const generation = lc.generation;
    const captureGeneration = lc.captureGeneration || 0;
    const stale = () => !lc.active || lc.muted || lc.generation !== generation || (lc.captureGeneration || 0) !== captureGeneration;
    if (!lc.active || !blob || !blob.size) { if (lc.active) resumeLiveListening(); return; }
    setLiveCallState('TRANSCRIBING');
    const form = new FormData();
    const baseType = String(blob.type || 'audio/webm').split(';', 1)[0];
    const extension = baseType.includes('ogg') ? 'ogg' : baseType.includes('wav') ? 'wav' : baseType.includes('mp4') || baseType.includes('m4a') ? 'm4a' : 'webm';
    form.append('audio', blob, `utterance.${extension}`);
    form.append('duration_ms', String(Math.max(1, Math.min(60000, Math.round(Number(durationMs) || 1)))));
    try {
      const response = await fetch('/api/stt/transcribe', {method:'POST', body:form});
      if (!response.ok) {
        let detail = `Local STT failed (${response.status})`; try { const body = await response.json(); detail = body.detail || detail; } catch {}
        const error = new Error(typeof detail === 'string' ? detail : 'Local STT failed'); error.status = response.status; throw error;
      }
      const result = await response.json();
      if (stale()) return;
      const transcript = String(result.text || '').trim();
      if (!transcript) { setLiveCallState('LISTENING', 'no speech'); resumeLiveListening(); return; }
      await handleLiveTranscript(transcript);
    } catch (error) {
      if (stale()) return;
      const allowBrowser = !!state.settings.stt_allow_browser_online;
      if (allowBrowser && browserSpeechRecognitionCtor()) {
        lc.mode = 'browser';
        setLiveCallState('LISTENING', 'browser fallback');
        startBrowserListening();
        return;
      }
      showToast(error.message || 'Local STT failed', {title:'Live Call', tone:'danger', duration:3600});
      if (lc.active) { setLiveCallState('LISTENING'); setTimeout(startLocalListening, 200); }
    }
  }

  function startLocalListening() {
    const lc = state.liveCall;
    if (!lc.active || lc.muted || lc.processing || lc.state === 'SPEAKING') return;
    if (!lc.stream?.active) { void ensureLocalMicStream().then(startLocalListening).catch(error => endLiveCall({error})); return; }
    if (typeof MediaRecorder === 'undefined') { endLiveCall({error:new Error('MediaRecorder is unavailable')}); return; }
    if (lc.recorder && lc.recorder.state !== 'inactive') return;
    lc.chunks = []; lc.recorderDiscard = false; lc.speechHeard = false; lc.lastVoiceAt = 0; lc.recordingStartedAt = performance.now();
    const mimeType = recorderMimeType();
    let recorder;
    try { recorder = new MediaRecorder(lc.stream, mimeType ? {mimeType} : undefined); }
    catch (error) { endLiveCall({error}); return; }
    lc.recorder = recorder;
    recorder.ondataavailable = event => { if (lc.recorder === recorder && event.data?.size) lc.chunks.push(event.data); };
    recorder.onerror = event => { showToast(event?.error?.message || 'Microphone recorder failed', {title:'Live Call', tone:'danger'}); };
    recorder.onstop = () => {
      if (lc.recorder !== recorder) return;
      const discard = lc.recorderDiscard;
      const chunks = lc.chunks.slice();
      const actualType = recorder.mimeType || mimeType || 'audio/webm';
      lc.recorder = null; lc.chunks = []; lc.recorderDiscard = false;
      if (!lc.active || lc.muted) return;
      if (discard || !lc.speechHeard) { if (lc.state === 'LISTENING') setTimeout(startLocalListening, 120); return; }
      const blob = new Blob(chunks, {type:actualType});
      const durationMs = Math.max(1, Math.min(60000, performance.now() - lc.recordingStartedAt));
      void transcribeLocalBlob(blob, durationMs);
    };
    recorder.start(250);
    setLiveCallState('LISTENING', 'local STT');
  }

  function startBrowserListening() {
    const lc = state.liveCall;
    if (!lc.active || lc.muted || lc.processing || lc.state === 'SPEAKING') return;
    const Ctor = browserSpeechRecognitionCtor();
    if (!Ctor || !state.settings.stt_allow_browser_online) {
      endLiveCall({error:new Error('Browser STT fallback is unavailable or not permitted')}); return;
    }
    stopBrowserRecognition();
    const recognition = new Ctor();
    lc.browserRecognition = recognition;
    recognition.lang = 'en-US'; recognition.continuous = false; recognition.interimResults = true; recognition.maxAlternatives = 1;
    let finalText = '';
    recognition.onresult = event => {
      if (lc.browserRecognition !== recognition || lc.muted) return;
      for (let i = event.resultIndex || 0; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText += `${result[0]?.transcript || ''} `;
      }
    };
    recognition.onerror = event => {
      if (['aborted','no-speech'].includes(String(event?.error || ''))) return;
      if (lc.active) showToast(`Browser STT · ${event?.error || 'failed'}`, {title:'Live Call', tone:'danger', duration:3000});
    };
    recognition.onend = () => {
      if (lc.browserRecognition !== recognition || lc.muted) return;
      if (lc.browserRecognition === recognition) lc.browserRecognition = null;
      const transcript = finalText.trim();
      if (transcript && lc.active && !lc.processing) { void handleLiveTranscript(transcript); return; }
      if (lc.active && !lc.muted && !lc.processing && lc.state === 'LISTENING' && lc.mode === 'browser') {
        lc.browserRestartTimer = setTimeout(startBrowserListening, 220);
      }
    };
    try { recognition.start(); setLiveCallState('LISTENING', 'Browser STT'); }
    catch (error) { endLiveCall({error}); }
  }

  function resumeLiveListening() {
    const lc = state.liveCall;
    if (!lc.active || lc.muted || lc.processing) return;
    setLiveCallState('LISTENING');
    if (lc.mode === 'browser') startBrowserListening(); else startLocalListening();
  }

  async function handleLiveTranscript(text) {
    const lc = state.liveCall;
    const transcript = String(text || '').trim();
    if (!lc.active || lc.muted || lc.processing || !transcript) return;
    lc.processing = true;
    stopLocalRecorder({discard:true}); stopBrowserRecognition();
    setLiveCallState('THINKING', transcript.length > 54 ? `${transcript.slice(0, 51)}…` : transcript);
    try {
      const completed = await sendChat(transcript, {suppressAutoSpeak:true});
      const assistant = String(completed?.assistant || '').trim();
      if (!lc.active) return;
      if (assistant) {
        setLiveCallState('SPEAKING');
        lc.speakerStartedAt = performance.now(); lc.bargeFrames = 0;
        await speakText(assistant);
      }
    } catch (error) {
      if (lc.active) showToast(error.message || 'Live turn failed', {title:'Live Call', tone:'danger', duration:3600});
    } finally {
      lc.processing = false;
      if (lc.active && lc.state !== 'LISTENING') resumeLiveListening();
    }
  }

  function sttPrepareMessage(local = {}) {
    const phase = String(local.prepare_state || '').toLowerCase();
    const message = String(local.prepare_message || '').trim();
    if (message) return message;
    if (phase === 'installing') return 'Installing local STT dependency…';
    if (phase === 'downloading') return 'Downloading local STT model…';
    if (phase === 'loading') return 'Loading local STT model…';
    if (phase === 'queued') return 'Starting local STT preparation…';
    return 'Preparing local STT…';
  }

  async function sttRequest(path, opts = {}, signal = null) {
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (signal?.aborted) controller.abort();
    signal?.addEventListener('abort', cancel, {once:true});
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; cancel(); }, 15000);
    try {
      if (controller.signal.aborted) throw new DOMException('Preparation cancelled', 'AbortError');
      return await api(path, {...opts, signal:controller.signal});
    } catch (error) {
      if (timedOut && !signal?.aborted) throw new Error('Local STT request timed out. Retry preparation.');
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
    }
  }

  async function pollLocalSTTPreparation({timeoutMs=15*60*1000, onStatus=null, signal=null} = {}) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const status = await sttRequest('/api/stt/status', {}, signal);
      if (signal?.aborted) throw new DOMException('Preparation cancelled', 'AbortError');
      const local = status.local || {};
      if (onStatus) onStatus(status);
      if (local.model_ready || String(local.prepare_state || '').toLowerCase() === 'ready') return status;
      if (String(local.prepare_state || '').toLowerCase() === 'error') {
        throw new Error(local.last_error || local.prepare_message || 'Local STT preparation failed');
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw new Error('Local STT preparation timed out. Check MatrixFiles/Voice/STT/prepare.log.');
  }

  async function prepareLiveCallSTT(signal) {
    const lc = state.liveCall;
    setLiveCallState('PREPARING', 'local STT');
    try {
      let status = await sttRequest('/api/stt/status', {}, signal);
      if (!status.local?.model_ready) {
        await sttRequest('/api/stt/prepare', {method:'POST'}, signal);
        status = await pollLocalSTTPreparation({signal, onStatus: current => setLiveCallState('PREPARING', sttPrepareMessage(current.local || {}))});
      }
      if (signal?.aborted) throw new DOMException('Preparation cancelled', 'AbortError');
      if (status.local?.model_ready) { lc.mode = 'local'; return 'local'; }
      throw new Error('Local STT did not become ready');
    } catch (error) {
      if (signal?.aborted) throw error;
      if (state.settings.stt_allow_browser_online && browserSpeechRecognitionCtor()) {
        lc.mode = 'browser'; return 'browser';
      }
      throw error;
    }
  }

  async function requestLiveMicrophonePermission() {
    if (!confirm('Allow microphone access?\n\nLive Call needs your microphone to hear you. Select OK to allow access and start the call, or Cancel to go back.')) return false;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone capture is unavailable in this WebView.');
    try {
      // Request system permission before downloading/preparing speech models.
      // Release this short check immediately; call capture starts when ready.
      const stream = await navigator.mediaDevices.getUserMedia({audio:true, video:false});
      stream.getTracks().forEach(track => track.stop());
      return true;
    } catch (error) {
      if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
        throw new Error('Microphone access was denied. Allow microphone access in Windows or browser settings, then try Live Call again.');
      }
      if (error.name === 'NotFoundError') throw new Error('No microphone was found. Connect a microphone and try Live Call again.');
      if (error.name === 'NotReadableError') throw new Error('The microphone could not be opened. Check whether another app is using it, then try again.');
      throw error;
    }
  }

  async function startLiveCall() {
    const lc = state.liveCall;
    if (lc.active) { await endLiveCall(); return; }
    if (state.abort) { showToast('Wait for the current model response to finish or stop it first.', {title:'Live Call', tone:'danger'}); return; }
    if (!state.settings.voice_output_enabled || String(state.settings.tts_provider || 'browser') === 'off') {
      showToast('Enable Voice Output and select a voice provider before starting Live Call.', {title:'Live Call', tone:'danger', duration:3600}); return;
    }
    lc.active = true; lc.muted = false; lc.processing = false; lc.generation += 1;
    const generation = lc.generation;
    const preparation = new AbortController();
    lc.preparation = preparation;
    setLiveCallState('PREPARING', 'microphone permission');
    try {
      const permitted = await requestLiveMicrophonePermission();
      if (!lc.active || lc.generation !== generation) return;
      if (!permitted) { await endLiveCall(); return; }
      const mode = await prepareLiveCallSTT(preparation.signal);
      if (!lc.active || lc.generation !== generation) return;
      if (mode === 'local') await ensureLocalMicStream();
      if (!lc.active || lc.generation !== generation) return;
      setLiveCallState('LISTENING');
      if (mode === 'local') startLocalListening(); else startBrowserListening();
    } catch (error) {
      if (lc.generation === generation) await endLiveCall({error});
    }
  }

  async function endLiveCall({error=null} = {}) {
    const lc = state.liveCall;
    lc.active = false; lc.processing = false; lc.generation += 1;
    lc.preparation?.abort(); lc.preparation = null;
    stopBrowserRecognition(); stopLocalRecorder({discard:true});
    if (lc.vadTimer) { clearInterval(lc.vadTimer); lc.vadTimer = null; }
    if (lc.stream) { for (const track of lc.stream.getTracks()) { try { track.stop(); } catch {} } lc.stream = null; }
    try { lc.source?.disconnect(); } catch {} lc.source = null; lc.analyser = null;
    if (lc.audioContext) { try { await lc.audioContext.close(); } catch {} lc.audioContext = null; }
    stopSpeech({notifyBackend:true, release:false});
    fetch('/api/stt/release', {method:'POST'}).catch(()=>{});
    lc.mode = 'local'; lc.muted = false; setLiveCallState('IDLE');
    if (error) showToast(error.message || 'Live Call ended', {title:'Live Call', tone:'danger', duration:4000});
  }

  function toggleLiveMute() {
    const lc = state.liveCall;
    if (!lc.active) return;
    lc.muted = !lc.muted;
    if (lc.muted) lc.captureGeneration = (lc.captureGeneration || 0) + 1;
    if (lc.stream) lc.stream.getAudioTracks().forEach(track => { track.enabled = !lc.muted; });
    if (lc.muted) { stopLocalRecorder({discard:true}); stopBrowserRecognition(); }
    setLiveCallState(lc.state);
    if (!lc.muted && !lc.processing && lc.state !== 'PREPARING') resumeLiveListening();
  }

  async function prepareLocalSTTFromSettings() {
    const button = $('#prepare-local-stt');
    if (button) { button.disabled = true; button.textContent = 'PREPARING…'; }
    const status = $('#stt-status');
    if (status) status.textContent = 'Starting local STT preparation…';
    try {
      const snapshot = collectSettings();
      state.settings = await persistSettingsSnapshot(snapshot);
      await sttRequest('/api/stt/prepare', {method:'POST'});
      const result = await pollLocalSTTPreparation({onStatus: current => {
        if (status) status.textContent = sttPrepareMessage(current.local || {});
      }});
      if (status) status.textContent = `Local STT ready · ${result.local?.model || state.settings.stt_local_model || 'base.en'} · CPU int8`;
    } catch (error) {
      const message = error.message || 'Local STT preparation failed';
      if (status) status.textContent = `${message} · see MatrixFiles/Voice/STT/prepare.log`;
      showToast(message, {title:'Voice', tone:'danger', duration:6000});
    } finally {
      if (button) { button.disabled = false; button.textContent = 'PREPARE LOCAL STT'; }
    }
  }

  function primeEdgeVoiceSelection(value) {
    const select = $('#set-tts-edge-voice');
    const voice = String(value || 'en-US-AvaNeural').trim() || 'en-US-AvaNeural';
    if (!select) return voice;
    if (![...select.options].some(option => option.value === voice)) {
      const option = document.createElement('option');
      option.value = voice;
      option.textContent = voice;
      select.appendChild(option);
    }
    select.value = voice;
    return voice;
  }

  function syncTTSProviderUI() {
    const provider = $('#set-tts-provider')?.value || state.settings.tts_provider || 'browser';
    const online = !!$('#set-tts-allow-online')?.checked;
    if ($('#tts-edge-voice-field')) $('#tts-edge-voice-field').hidden = provider !== 'edge';
    if ($('#tts-local-voice-field')) $('#tts-local-voice-field').hidden = provider !== 'local';
    if ($('#tts-edge-fallback-field')) $('#tts-edge-fallback-field').hidden = provider !== 'edge';
    for (const id of ['tts-edge-tone-field','tts-edge-intensity-field','tts-edge-pause-field']) { const el = $('#'+id); if (el) el.hidden = provider !== 'edge'; }
    const edgeSelect = $('#set-tts-edge-voice');
    const refresh = $('#refresh-edge-voices');
    if (edgeSelect) edgeSelect.disabled = provider !== 'edge' || !online || state.edgeVoicesLoading;
    if (refresh) refresh.disabled = provider !== 'edge' || !online || state.edgeVoicesLoading;
    const edgeStatus = $('#edge-voice-status');
    if (edgeStatus && provider === 'edge' && !online) edgeStatus.textContent = 'Enable online Edge TTS to load the full Microsoft voice catalog.';
  }

  function edgeVoiceLabel(voice) {
    const name = String(voice?.friendly_name || voice?.short_name || '').trim();
    const locale = String(voice?.locale || '').trim();
    const gender = String(voice?.gender || '').trim();
    return [name, locale, gender].filter(Boolean).join(' · ');
  }

  async function loadEdgeVoices({force=false} = {}) {
    const provider = $('#set-tts-provider')?.value || state.settings.tts_provider || 'browser';
    const online = !!$('#set-tts-allow-online')?.checked;
    const select = $('#set-tts-edge-voice');
    const status = $('#edge-voice-status');
    if (!select || provider !== 'edge' || !online) { syncTTSProviderUI(); return []; }
    if (state.edgeVoicesLoaded && !force) return [...select.options].map(option => option.value);
    if (state.edgeVoicesLoading) return [];

    state.edgeVoicesLoading = true;
    syncTTSProviderUI();
    if (status) status.textContent = 'Preparing Edge support and loading voices…';
    try {
      // Persist the privacy gate before the backend is allowed to make the
      // Microsoft voice-catalog request. This avoids the old autosave race.
      const saved = await api('/api/settings', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({tts_provider:'edge', tts_allow_online:true})
      });
      if (saved?.settings) state.settings = {...state.settings, ...saved.settings};
      await api('/api/tts/edge/prepare', {method:'POST'});
      const result = await api('/api/tts/voices/edge' + (force ? '?refresh=1' : ''));
      const voices = Array.isArray(result?.voices) ? result.voices : [];
      if (!voices.length) throw new Error('No Edge voices were returned');

      const previous = select.value || state.settings.tts_edge_voice || 'en-US-AvaNeural';
      const sorted = [...voices].sort((a,b) => {
        const locale = String(a.locale || '').localeCompare(String(b.locale || ''));
        return locale || edgeVoiceLabel(a).localeCompare(edgeVoiceLabel(b));
      });
      select.replaceChildren();
      for (const voice of sorted) {
        if (!voice?.short_name) continue;
        const option = document.createElement('option');
        option.value = voice.short_name;
        option.textContent = edgeVoiceLabel(voice);
        select.appendChild(option);
      }
      const available = [...select.options].map(option => option.value);
      const preferred = available.includes(previous) ? previous : (available.includes('en-US-AvaNeural') ? 'en-US-AvaNeural' : available[0]);
      if (preferred) select.value = preferred;
      state.settings.tts_edge_voice = select.value;
      state.edgeVoicesLoaded = true;
      if (status) status.textContent = `${available.length} Edge voices loaded · ${select.value}`;
      return sorted;
    } catch (error) {
      state.edgeVoicesLoaded = false;
      if (status) status.textContent = `Edge voices unavailable · ${error.message || error}`;
      throw error;
    } finally {
      state.edgeVoicesLoading = false;
      syncTTSProviderUI();
    }
  }

  async function handleTTSProviderChange() {
    if (state.liveCall.active) await endLiveCall();
    const provider = $('#set-tts-provider').value;
    state.settings.tts_provider = provider;
    stopSpeech({notifyBackend:true, release:provider !== 'local'});
    syncTTSProviderUI();
    try {
      const saved = await persistSettingsSnapshot(collectSettings());
      state.settings = {...state.settings, ...saved};
      if (provider === 'edge' && $('#set-tts-allow-online').checked) await loadEdgeVoices({force:true});
      await refreshTTSStatus();
    } catch (error) {
      if ($('#tts-status')) $('#tts-status').textContent = error.message || 'Voice provider switch failed';
    }
  }

  async function handleTTSOnlineChange() {
    state.settings.tts_allow_online = !!$('#set-tts-allow-online').checked;
    stopSpeech({notifyBackend:true, release:false});
    syncTTSProviderUI();
    try {
      const saved = await persistSettingsSnapshot(collectSettings());
      state.settings = {...state.settings, ...saved};
      if (state.settings.tts_allow_online && $('#set-tts-provider').value === 'edge') await loadEdgeVoices({force:true});
      await refreshTTSStatus();
    } catch (error) {
      if ($('#tts-status')) $('#tts-status').textContent = error.message || 'Online voice setting failed';
    }
  }

  function armMotion() {
    const body = document.body;
    body.classList.remove('motion-ready', 'ambient-ready');
    body.classList.add('motion-prewarm');
    // Give WebView2 a few idle frames to allocate compositor layers before
    // the visible entrance starts. This avoids the one-time first-animation hitch.
    requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => {
      setTimeout(() => body.classList.add('motion-ready'), 70);
      setTimeout(() => body.classList.add('ambient-ready'), 980);
      setTimeout(() => body.classList.remove('motion-prewarm'), 1400);
    })));
  }
  function setComposeStatus(text) { $('#compose-status').textContent = text; }
  function syncGenerationState() {
    const phase = state.generationPhase || 'ready';
    document.body.dataset.generationPhase = phase;
    $('.composer')?.classList.toggle('is-busy', ['thinking', 'generating'].includes(phase));
  }
  function setGenerationPhase(phase, text='') {
    state.generationPhase = phase || 'ready';
    syncGenerationState();
    if (text) setComposeStatus(text);
  }


  const THINK_MODE_INFO = {
    auto: {label:'AUTO THINK', meta:'Balanced routing', detail:'Lets MatrixStudio choose the lightest useful path for the next reply.'},
    standard: {label:'STANDARD THINK', meta:'Visible reasoning', detail:'Uses a moderate reasoning pass for clearer multi-step work.'},
    deep: {label:'DEEP REASONING', meta:'Maximum deliberation', detail:'Spends more time reasoning through difficult tasks before answering.'}
  };

  function buildAmbientParticles() {
    const host = $('#ambient-particles');
    if (!host || host.childElementCount) return;
    host.replaceChildren();
    const count = 18;
    for (let i = 0; i < count; i++) {
      const particle = document.createElement('span');
      particle.style.setProperty('--size', `${Math.round(5 + Math.random() * 18)}px`);
      particle.style.setProperty('--x', `${Math.round(Math.random() * 100)}%`);
      particle.style.setProperty('--y', `${Math.round(Math.random() * 100)}%`);
      particle.style.setProperty('--delay', `${(-Math.random() * 16).toFixed(2)}s`);
      particle.style.setProperty('--duration', `${(10 + Math.random() * 14).toFixed(2)}s`);
      particle.style.setProperty('--drift', `${Math.round(Math.random() * 180 - 90)}px`);
      particle.style.setProperty('--rise', `${Math.round(60 + Math.random() * 160)}px`);
      particle.style.setProperty('--alpha', `${(0.11 + Math.random() * 0.18).toFixed(2)}`);
      host.append(particle);
    }
  }

  function thinkModeInfo(value) {
    return THINK_MODE_INFO[String(value || 'auto').toLowerCase()] || THINK_MODE_INFO.auto;
  }

  function sessionGenerationProfile() {
    const raw = state.session?.generation_profile || {};
    return {
      model: String(raw.model || state.settings.ollama_chat_model || state.runtime.selected_model || '').trim(),
      think_mode: String(raw.think_mode || state.settings.think_mode || 'auto').toLowerCase(),
      locked: !!raw.locked || !!(state.session?.messages || []).length
    };
  }

  function sessionControlsLocked() {
    return sessionGenerationProfile().locked;
  }

  function syncSessionGenerationControls() {
    const profile = sessionGenerationProfile();
    const model = $('#quick-model');
    const think = $('#quick-think');
    if (model && profile.model) model.value = profile.model;
    if (think) think.value = profile.think_mode || 'auto';
    syncQuickControlLabels();
  }

  function setMenuTriggerState(trigger, open) {
    if (trigger) trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  function syncQuickControlLabels() {
    const profile = sessionGenerationProfile();
    const selectedModel = profile.model;
    const locked = profile.locked;
    const modelLabel = $('#quick-model-label');
    const modelMeta = $('#quick-model-meta');
    const modelTrigger = $('#quick-model-trigger');
    if (modelLabel) modelLabel.textContent = selectedModel || 'No local model';
    if (modelMeta) {
      if (!selectedModel) modelMeta.textContent = state.runtime.ok ? 'No local model selected' : 'Runtime offline';
      else if (locked) modelMeta.textContent = 'Locked to this chat';
      else if ((state.runtime.loaded_models || []).includes(selectedModel)) modelMeta.textContent = 'Loaded locally · editable until first message';
      else modelMeta.textContent = state.runtime.ok ? 'Portable store · editable until first message' : 'Runtime offline';
    }
    if (modelTrigger) {
      modelTrigger.disabled = !!state.abort || !(state.runtime.models || []).length || locked;
      modelTrigger.title = locked ? 'Start a new chat to change the model.' : 'Choose the model for this new chat.';
    }

    const think = thinkModeInfo(profile.think_mode);
    const thinkLabel = $('#quick-think-label');
    const thinkMeta = $('#quick-think-meta');
    const thinkTrigger = $('#quick-think-trigger');
    if (thinkLabel) thinkLabel.textContent = think.label;
    if (thinkMeta) thinkMeta.textContent = locked ? `${think.meta} · locked to chat` : `${think.meta} · editable until first message`;
    if (thinkTrigger) {
      thinkTrigger.disabled = !!state.abort || locked;
      thinkTrigger.title = locked ? 'Start a new chat to change reasoning mode.' : 'Choose reasoning for this new chat.';
    }
    const modelSelect = $('#quick-model');
    const thinkSelect = $('#quick-think');
    if (modelSelect) modelSelect.disabled = !!state.abort || !state.runtime.model_ready || locked;
    if (thinkSelect) thinkSelect.disabled = !!state.abort || locked;
  }

  function controlMenuSpec() {
    const type = state.controlMenu?.type;
    if (type === 'think') {
      return {
        kicker: 'REASONING',
        title: 'Reasoning mode',
        copy: 'Choose how much deliberation the model should spend on the next replies.',
        foot: 'Applies to new responses only.',
        searchable: false,
        items: Object.entries(THINK_MODE_INFO).map(([value, info]) => ({
          value,
          label: info.label,
          meta: info.meta,
          detail: info.detail,
          active: sessionGenerationProfile().think_mode === value,
          badges: value === 'deep' ? ['HEAVY'] : value === 'standard' ? ['TRACE'] : ['SMART'],
          action: () => {
            $('#quick-think').value = value;
            $('#quick-think').dispatchEvent(new Event('change', {bubbles:true}));
            closeControlMenu();
          }
        }))
      };
    }
    const models = state.runtime.models || [];
    const selected = sessionGenerationProfile().model;
    const loaded = new Set(state.runtime.loaded_models || []);
    return {
      kicker: 'MODEL',
      title: 'Portable models',
      copy: 'Choose the active local model for this chat. Only models in this project store appear here.',
      foot: `${models.length} installed · ${loaded.size} loaded`,
      searchable: models.length > 6,
      items: models.map(model => {
        const name = model.name || model.model;
        const loadedInfo = (state.runtime.loaded_model_details || []).find(x => (x.name || x.model) === name);
        const extras = [];
        if (loadedInfo?.size_vram) extras.push(`${fmtBytes(loadedInfo.size_vram)} VRAM`);
        if (loadedInfo?.context_length) extras.push(`${Number(loadedInfo.context_length).toLocaleString()} ctx`);
        return {
          value: name,
          label: name,
          meta: modelDetailText(model),
          detail: extras.join(' · ') || 'Available in the project-local Ollama store.',
          active: name === selected,
          badges: [name === selected ? 'ACTIVE' : '', loaded.has(name) ? 'LOADED' : ''].filter(Boolean),
          action: () => {
            $('#quick-model').value = name;
            $('#quick-model').dispatchEvent(new Event('change', {bubbles:true}));
            closeControlMenu();
          }
        };
      })
    };
  }

  function renderControlMenuList() {
    const list = $('#control-menu-list');
    if (!list) return;
    const spec = controlMenuSpec();
    const q = String(state.controlMenu?.filter || '').trim().toLowerCase();
    const items = (spec.items || []).filter(item => !q || `${item.label} ${item.meta || ''} ${item.detail || ''}`.toLowerCase().includes(q));
    $('#control-menu-kicker').textContent = spec.kicker;
    $('#control-menu-title').textContent = spec.title;
    $('#control-menu-copy').textContent = spec.copy;
    $('#control-menu-foot').textContent = spec.foot;
    const searchWrap = $('#control-menu-search-wrap');
    searchWrap.hidden = !spec.searchable;
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'control-menu-empty';
      empty.textContent = spec.items?.length ? 'No options match that filter.' : 'Nothing available here yet.';
      list.append(empty);
      return;
    }
    for (const item of items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `control-menu-option${item.active ? ' active' : ''}`;
      const copy = document.createElement('div');
      copy.className = 'control-menu-option-copy';
      const titleRow = document.createElement('div');
      titleRow.className = 'control-menu-option-title';
      const strong = document.createElement('strong');
      strong.textContent = item.label;
      titleRow.append(strong);
      const tags = (item.badges || []).filter(Boolean);
      if (tags.length) {
        const tagWrap = document.createElement('div');
        tagWrap.className = 'control-menu-option-tags';
        for (const tag of tags) {
          const span = document.createElement('span');
          span.className = 'control-menu-tag';
          span.textContent = tag;
          tagWrap.append(span);
        }
        titleRow.append(tagWrap);
      }
      const meta = document.createElement('span');
      meta.className = 'control-menu-option-meta';
      meta.textContent = item.meta || '';
      const detail = document.createElement('small');
      detail.textContent = item.detail || '';
      copy.append(titleRow, meta, detail);
      const marker = document.createElement('span');
      marker.className = 'control-menu-option-marker';
      marker.textContent = item.active ? '●' : '○';
      button.append(copy, marker);
      button.addEventListener('click', item.action);
      list.append(button);
    }
  }

  function positionControlMenu() {
    const panel = $('#control-menu-panel');
    const layer = $('#control-menu-layer');
    const trigger = state.controlMenu?.trigger;
    if (!panel || !layer || layer.hidden || !trigger) return;
    const rect = trigger.getBoundingClientRect();
    const panelWidth = Math.min(380, Math.max(300, Math.round(window.innerWidth * 0.34)));
    const left = Math.max(12, Math.min(window.innerWidth - panelWidth - 12, rect.right - panelWidth));
    const top = Math.min(window.innerHeight - 16, rect.bottom + 10);
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    panel.style.width = `${panelWidth}px`;
  }

  function closeControlMenu({focus=false} = {}) {
    const layer = $('#control-menu-layer');
    if (!layer || layer.hidden) return;
    const trigger = state.controlMenu?.trigger;
    layer.classList.remove('open');
    layer.hidden = true;
    setMenuTriggerState(trigger, false);
    $('#control-menu-search').value = '';
    state.controlMenu = null;
    if (focus && trigger) trigger.focus({preventScroll:true});
  }

  function openControlMenu(type, trigger) {
    const layer = $('#control-menu-layer');
    if (!layer || !trigger) return;
    const same = !layer.hidden && state.controlMenu?.type === type && state.controlMenu?.trigger === trigger;
    if (same) { closeControlMenu({focus:true}); return; }
    closeControlMenu();
    state.controlMenu = {type, trigger, filter:''};
    setMenuTriggerState(trigger, true);
    layer.hidden = false;
    renderControlMenuList();
    positionControlMenu();
    requestAnimationFrame(() => layer.classList.add('open'));
    const searchWrap = $('#control-menu-search-wrap');
    const target = searchWrap.hidden ? $('#control-menu-list .control-menu-option') : $('#control-menu-search');
    setTimeout(() => target?.focus({preventScroll:true}), 20);
  }

  function dismissToast({immediate=false} = {}) {
    const toast = $('#app-toast');
    if (!toast) return;
    clearTimeout(state.toastTimer);
    toast.classList.remove('show');
    if (immediate) toast.replaceChildren();
  }

  function showToast(message, {label='', action=null, duration=5200, tone='info', title=''} = {}) {
    const toast = $('#app-toast');
    if (!toast) return;
    clearTimeout(state.toastTimer);
    toast.replaceChildren();
    toast.dataset.tone = tone || 'info';
    toast.style.setProperty('--toast-duration', `${Math.max(900, Number(duration) || 5200)}ms`);

    const icon = document.createElement('span');
    icon.className = 'app-toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = tone === 'danger' ? '×' : tone === 'success' ? '✓' : tone === 'accent' ? '◇' : '·';

    const copy = document.createElement('div');
    copy.className = 'app-toast-copy';
    if (title) {
      const heading = document.createElement('strong');
      heading.textContent = title;
      copy.append(heading);
    }
    const text = document.createElement('span');
    text.className = 'app-toast-message';
    text.textContent = message;
    copy.append(text);

    const actions = document.createElement('div');
    actions.className = 'app-toast-actions';
    if (label && typeof action === 'function') {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'app-toast-action';
      btn.textContent = label;
      btn.addEventListener('click', async () => {
        dismissToast();
        try { await action(); } catch (e) { setComposeStatus(e.message || 'Action failed'); }
      });
      actions.append(btn);
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'app-toast-close';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.textContent = '×';
    close.addEventListener('click', () => dismissToast());
    actions.append(close);

    const progress = document.createElement('span');
    progress.className = 'app-toast-progress';
    progress.setAttribute('aria-hidden', 'true');

    toast.append(icon, copy, actions, progress);
    requestAnimationFrame(() => toast.classList.add('show'));
    state.toastTimer = setTimeout(() => dismissToast(), Math.max(900, Number(duration) || 5200));
  }
  function persistUiState(patch, delay = 140) {
    state.uiState = {...(state.uiState || {}), ...patch};
    clearTimeout(state.uiStateTimer);
    state.uiStateTimer = setTimeout(() => {
      fetch('/api/ui-state', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(state.uiState)}).catch(()=>{});
    }, delay);
  }

  function sessionViewSnapshot() {
    const sid = state.session?.id || '';
    const input = $('#chat-input');
    const box = $('#messages');
    const drafts = {...(state.uiState?.session_drafts || {})};
    const scrolls = {...(state.uiState?.session_scroll || {})};
    if (sid) {
      drafts[sid] = input?.value || '';
      scrolls[sid] = Math.max(0, Math.round(box?.scrollTop || 0));
    }
    return {...(state.uiState || {}), active_session_id:sid, draft:input?.value || '', session_drafts:drafts, session_scroll:scrolls};
  }

  function persistCurrentSessionView(delay = 80) {
    const snapshot = sessionViewSnapshot();
    state.uiState = snapshot;
    persistUiState({active_session_id:snapshot.active_session_id, draft:snapshot.draft, session_drafts:snapshot.session_drafts, session_scroll:snapshot.session_scroll}, delay);
  }

  function draftForSession(sid) {
    if (!sid) return '';
    const drafts = state.uiState?.session_drafts || {};
    if (Object.prototype.hasOwnProperty.call(drafts, sid)) return String(drafts[sid] || '');
    if (state.uiState?.active_session_id === sid) return String(state.uiState?.draft || '');
    return '';
  }

  function savedScrollForSession(sid) {
    const raw = state.uiState?.session_scroll?.[sid];
    return Number.isFinite(Number(raw)) ? Math.max(0, Number(raw)) : null;
  }
  function fmtTime(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString([], { month:'short', day:'numeric', hour:'numeric', minute:'2-digit' }); } catch { return ''; }
  }
  function fmtBytes(n) {
    n = Number(n || 0); if (!n) return '';
    const units = ['B','KB','MB','GB','TB']; let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i >= 3 ? 1 : 0)} ${units[i]}`;
  }
  function statsText(s = {}) {
    const chunks = [];
    if (s.generated_tokens) chunks.push(`${s.generated_tokens} generated`);
    if (s.prompt_tokens) chunks.push(`${s.prompt_tokens} prompt`);
    if (s.tokens_per_second) chunks.push(`${s.tokens_per_second} tok/s`);
    if (s.elapsed_seconds) chunks.push(`${s.elapsed_seconds}s`);
    return chunks.join(' · ');
  }

  function applyAppearance(s = state.settings) {
    const body = document.body;
    body.dataset.theme = s.theme_preset || 'matrix';
    body.dataset.mode = s.ui_mode || 'dark';
    const uiScale = clamp(Number(s.ui_font_scale || 1), .75, 1.4);
    const densityScale = s.ui_density === 'compact' ? .90 : 1;
    const geometryScale = uiScale * densityScale;
    document.documentElement.style.setProperty('--ui-scale', uiScale);
    body.style.setProperty('--sidebar-width', `${Math.round(284 * geometryScale)}px`);
    body.style.setProperty('--topbar-height', `${Math.round(56 * geometryScale)}px`);
    body.style.setProperty('--control-height', `${Math.round(34 * geometryScale)}px`);
    body.style.setProperty('--quick-model-width', `${Math.round(224 * geometryScale)}px`);
    body.style.setProperty('--quick-reason-width', `${Math.round(150 * geometryScale)}px`);
    body.style.setProperty('--settings-control-height', `${Math.round(39 * geometryScale)}px`);
    body.style.setProperty('--settings-tab-height', `${Math.round(43 * geometryScale)}px`);
    body.style.setProperty('--settings-nav-width', `${Math.round(190 * geometryScale)}px`);
    body.style.setProperty('--settings-dialog-width', `${Math.round(1040 * geometryScale)}px`);
    body.style.setProperty('--settings-head-height', `${Math.round(92 * geometryScale)}px`);
    body.style.setProperty('--settings-foot-height', `${Math.round(62 * geometryScale)}px`);
    body.style.setProperty('--chat-scale', Number(s.chat_font_scale || 1));
    const imageOpacity = clamp(Number(s.background_image_opacity ?? .62), 0, 1);
    body.style.setProperty('--workspace-bg-opacity', imageOpacity);
    const edgeBlur = clamp(Number(s.background_blur ?? 16), 0, 36);
    body.style.setProperty('--workspace-edge-blur', `${edgeBlur}px`);
    body.dataset.edgeFill = edgeBlur > 0.5 ? 'on' : 'off';
    const bgDim = clamp(Number(s.background_dim ?? .42), 0, .95);
    body.style.setProperty('--workspace-bg-dim', bgDim);
    const effectiveBgDim = clamp(1 - imageOpacity * (1 - bgDim), 0, .98);
    body.style.setProperty('--workspace-bg-effective-dim', effectiveBgDim);
    body.style.setProperty('--workspace-bg-dim-pct', `${Math.round(bgDim * 100)}%`);
    body.style.setProperty('--workspace-bg-dim-strong-pct', `${Math.round(clamp(bgDim + .18, 0, 1) * 100)}%`);
    body.style.setProperty('--workspace-bg-scale', 1);
    const panelOpacity = clamp(Number(s.panel_opacity ?? .88), .45, 1);
    const panelBlur = clamp(Number(s.panel_blur ?? 18), 0, 32);
    body.style.setProperty('--panel-opacity', `${Math.round(panelOpacity * 100)}%`);
    body.style.setProperty('--panel-opacity-soft', `${Math.round(clamp(panelOpacity - .06, .35, 1) * 100)}%`);
    body.style.setProperty('--panel-opacity-message', `${Math.round(clamp(panelOpacity - .10, .30, 1) * 100)}%`);
    body.style.setProperty('--panel-blur', `${panelBlur}px`);
    body.style.setProperty('--panel-blur-soft', `${panelBlur * .72}px`);
    body.style.setProperty('--panel-blur-message', `${panelBlur * .55}px`);
    body.style.setProperty('--panel-blur-dialog', `${panelBlur + 6}px`);
    body.style.setProperty('--glow-strength', `${Math.round(clamp(Number(s.glow_strength ?? .32), 0, 1) * 34)}%`);
    body.dataset.gradients = s.gradients_enabled ? 'on' : 'off';
    const gradientStrength = clamp(Number(s.gradient_strength ?? .42), 0, 1);
    body.style.setProperty('--gradient-strength', gradientStrength);
    body.style.setProperty('--gradient-soft', `${Math.round((2 + gradientStrength * 8) * 10) / 10}%`);
    body.style.setProperty('--gradient-medium', `${Math.round((4 + gradientStrength * 16) * 10) / 10}%`);
    body.style.setProperty('--gradient-strong', `${Math.round((8 + gradientStrength * 24) * 10) / 10}%`);
    // Background composition is intentionally fixed: preserve the source image's aspect ratio.
    // Only the separate edge-fill layer may crop/blur to fill unused workspace space.
    body.dataset.backgroundFit = 'preserve';
    body.style.setProperty('--workspace-bg-fit', 'contain');
    const imageOn = !!s.background_image_enabled;
    body.classList.toggle('background-image-active', imageOn);
    const imageVersion = Number(s.background_image_version || 0);
    const backgroundUrl = imageOn ? `/api/appearance/background?v=${imageVersion}` : '';
    body.style.setProperty('--workspace-bg-image', imageOn ? `url("${backgroundUrl}")` : 'none');
    if (!imageOn) { loadBackgroundMetrics(''); }
    else if (backgroundAsset.url !== backgroundUrl) { loadBackgroundMetrics(backgroundUrl); }
    else { requestAnimationFrame(layoutBackgroundEdges); }
    const custom = !!s.custom_colors_enabled;
    const colors = {
      '--accent': s.accent_color || '#66e2ba',
      '--accent-strong': s.accent_secondary || '#24d49a',
      '--bg': s.background_color || '#07100d',
      '--bg-deep': `color-mix(in srgb, ${s.background_color || '#07100d'} 82%, #000000)`,
      '--panel': s.panel_color || '#0a1215',
      '--panel-soft': `color-mix(in srgb, ${s.panel_color || '#0a1215'} 94%, ${s.ui_mode === 'light' ? '#000000' : '#ffffff'})`,
      '--user': s.user_bubble_color || '#15302a',
      '--assistant': s.assistant_bubble_color || '#111b22',
      '--muted': s.muted_text_color || '#82969a',
      '--muted2': s.muted_text_color || '#82969a'
    };
    for (const [key, value] of Object.entries(colors)) {
      if (custom) body.style.setProperty(key, value); else body.style.removeProperty(key);
    }
    body.classList.toggle('custom-colors', custom);
    body.classList.toggle('density-compact', s.ui_density === 'compact');
    const reduceMotion = boolValue(s.reduce_motion);
    body.classList.toggle('reduce-motion', reduceMotion);
    body.classList.toggle('motion-enabled', !reduceMotion);
  }

  function installedNames(runtime = state.runtime) {
    return (runtime.models || []).map(m => m.name || m.model).filter(Boolean);
  }

  function fillModelSelect(select, models, selected) {
    const names = (models || []).map(m => m.name || m.model).filter(Boolean);
    select.replaceChildren();
    if (!names.length) {
      const o = document.createElement('option');
      o.value = ''; o.textContent = 'No local models installed';
      select.append(o); select.disabled = true;
      syncQuickControlLabels();
      return;
    }
    for (const name of names) {
      const o = document.createElement('option'); o.value = name; o.textContent = name; select.append(o);
    }
    select.disabled = false;
    select.value = names.includes(selected) ? selected : names[0];
    syncQuickControlLabels();
  }

  function modelDetailText(model = {}) {
    const d = model.details || {};
    const chunks = [];
    if (d.parameter_size) chunks.push(String(d.parameter_size));
    if (d.quantization_level) chunks.push(String(d.quantization_level));
    if (d.family) chunks.push(String(d.family));
    if (model.size) chunks.push(fmtBytes(model.size));
    return chunks.filter(Boolean).join(' · ') || 'Local Ollama model';
  }

  async function deleteModel(name) {
    const modelName = String(name || '').trim();
    if (!modelName || state.abort) return;
    const warning = `Delete local model "${modelName}"?\n\nThis removes the model from MatrixStudio's project-local Ollama store. Existing chats keep the historical model name but cannot generate with it unless you reinstall it.`;
    if (!confirm(warning)) return;
    setComposeStatus(`Deleting ${modelName}…`);
    try {
      const data = await api(`/api/llm/models/${encodeURIComponent(modelName)}`, {method:'DELETE'});
      state.settings = data.settings || state.settings;
      state.runtime = data.runtime || await api('/api/llm/status');
      if (state.session?.id && !sessionControlsLocked() && sessionGenerationProfile().model === modelName) {
        const replacement = String(state.settings.ollama_chat_model || state.runtime.selected_model || '').trim();
        if (replacement) {
          const patched = await api(`/api/sessions/${encodeURIComponent(state.session.id)}/generation`, {
            method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model:replacement})
          }).catch(()=>null);
          if (patched?.session) state.session = patched.session;
        } else {
          state.session.generation_profile = {...(state.session.generation_profile || {}), model:'', locked:false};
        }
      }
      renderRuntime(state.runtime);
      fillSettingsForm(true);
      renderChat('keep');
      showToast(`Deleted ${modelName}`, {title:'Model manager', tone:'success', duration:2600});
      setComposeStatus((state.runtime.models || []).length ? 'Model deleted · ready' : 'Model deleted · install a model to continue');
    } catch (e) {
      setComposeStatus(`Delete failed · ${e.message}`);
      showToast(e.message, {title:'Delete failed', tone:'danger', duration:3600});
      await refreshRuntime({silent:true}).catch(()=>{});
    }
  }

  function renderModelManager(runtime = state.runtime) {
    const host = $('#model-manager-list'); if (!host) return;
    host.replaceChildren();
    const models = runtime.models || [];
    const selected = runtime.selected_model || state.settings.ollama_chat_model || '';
    const loaded = new Set(runtime.loaded_models || []);
    $('#model-manager-summary').textContent = `${models.length} installed · ${loaded.size} loaded`;
    if (!models.length) {
      const empty = document.createElement('div'); empty.className = 'model-manager-empty';
      empty.textContent = runtime.ok ? 'No models are installed in this portable store.' : 'Runtime unavailable — reconnect to inspect installed models.';
      host.append(empty); return;
    }
    for (const model of models) {
      const name = model.name || model.model; if (!name) continue;
      const row = document.createElement('div'); row.className = 'model-manager-row';
      const copy = document.createElement('div'); copy.className = 'model-manager-copy';
      const title = document.createElement('div'); title.className = 'model-manager-title';
      const strong = document.createElement('strong'); strong.textContent = name; title.append(strong);
      if (name === selected) { const tag=document.createElement('span'); tag.className='model-badge selected'; tag.textContent='SELECTED'; title.append(tag); }
      if (loaded.has(name)) { const tag=document.createElement('span'); tag.className='model-badge loaded'; tag.textContent='LOADED'; title.append(tag); }
      const meta = document.createElement('span'); meta.className='model-manager-meta';
      const loadedInfo = (runtime.loaded_model_details || []).find(x => (x.name || x.model) === name);
      const extras = [];
      if (loadedInfo?.size_vram) extras.push(`${fmtBytes(loadedInfo.size_vram)} VRAM`);
      if (loadedInfo?.processor) extras.push(loadedInfo.processor);
      if (loadedInfo?.context_length) extras.push(`${Number(loadedInfo.context_length).toLocaleString()} ctx`);
      meta.textContent = [modelDetailText(model), ...extras].filter(Boolean).join(' · ');
      copy.append(title, meta);
      const actions = document.createElement('div'); actions.className='model-manager-actions';
      const use = document.createElement('button'); use.type='button'; use.className='btn ghost small'; use.textContent = name === selected ? 'USING' : 'USE'; use.disabled = name === selected;
      use.disabled = !!state.abort || name === selected; use.addEventListener('click', async ()=>{ await quickPatch({ollama_chat_model:name}); await refreshRuntime({silent:true}); });
      const warm = document.createElement('button'); warm.type='button'; warm.className='btn ghost small'; warm.textContent='WARM';
      warm.disabled = !!state.abort; warm.addEventListener('click', async ()=>{
        try {
          if (name !== (state.settings.ollama_chat_model || '')) await quickPatch({ollama_chat_model:name});
          setComposeStatus(`Warming ${name}…`);
          await api('/api/llm/warm',{method:'POST'});
          await refreshRuntime({silent:true}); setComposeStatus(`Warm · ${name}`);
        } catch(e) { setComposeStatus(`Warm failed · ${e.message}`); }
      });
      const remove = document.createElement('button'); remove.type='button'; remove.className='btn ghost small model-delete'; remove.textContent='DELETE'; remove.title=`Delete ${name}`;
      remove.disabled = !!state.abort || !runtime.ok; remove.addEventListener('click', () => deleteModel(name));
      actions.append(use, warm, remove); row.append(copy, actions); host.append(row);
    }
  }

  function renderRuntime(runtime = state.runtime) {
    const runtimeState = String(runtime.state || (runtime.ok ? 'online' : 'offline')).toLowerCase();
    const online = runtimeState !== 'offline' && !!runtime.ok;
    const busy = runtimeState === 'busy' || !!runtime.busy || !!runtime.active_generations || ['starting','thinking','generating'].includes(state.generationPhase);
    const ready = online && !!runtime.model_ready;
    const dot = $('#runtime-dot');
    dot.className = `status-dot ${!online ? 'bad' : (busy || !ready) ? 'warn' : 'ok'}`;
    $('#runtime-label').textContent = !online ? 'Local runtime offline' : busy ? 'Local runtime active' : ready ? 'Local runtime online' : 'Runtime online · model required';
    $('#runtime-endpoint').textContent = runtime.endpoint || '127.0.0.1';
    $('#set-runtime-state').textContent = !online ? 'OFFLINE' : busy ? 'ACTIVE / BUSY' : ready ? 'READY' : 'WAITING FOR MODEL';
    $('#set-runtime-count').textContent = `${runtime.model_count ?? installedNames(runtime).length} installed`;
    $('#set-runtime-selected').textContent = runtime.selected_model || 'None';
    $('#set-runtime-vram').textContent = runtime.loaded_vram_bytes ? fmtBytes(runtime.loaded_vram_bytes) : ((runtime.loaded_models || []).length ? 'Reported by Ollama: —' : 'None loaded');
    $('#set-runtime-processor').textContent = runtime.selected_processor || ((runtime.loaded_models || []).length ? 'Unknown' : 'Not loaded');
    $('#set-runtime-endpoint').textContent = runtime.endpoint || '—';
    $('#set-runtime-store').textContent = runtime.model_store || '—';
    $('#set-runtime-loaded').textContent = (runtime.loaded_models || []).join(', ') || 'None';
    const age = Number(runtime.last_ok_age);
    $('#set-runtime-health').textContent = !online ? (runtime.error || 'No successful runtime probe') : busy && runtime.probe_error ? 'Alive · status probe delayed while busy' : Number.isFinite(age) ? `Healthy · last success ${age < 1 ? '<1' : Math.round(age)}s ago` : 'Healthy';

    if (runtime.model_ready && runtime.selected_model) state.settings.ollama_chat_model = runtime.selected_model;
    fillModelSelect($('#quick-model'), runtime.models, sessionGenerationProfile().model);
    fillModelSelect($('#set-model'), runtime.models, state.settings.ollama_chat_model);
    syncQuickControlLabels();
    renderModelManager(runtime);

    const starter = runtime.starter_model || 'llama3.2:3b';
    $('#starter-chip').textContent = starter;
    $('#model-alert').hidden = ready;
    $('#model-alert-reconnect').hidden = online;
    $('#install-starter').hidden = !online || ready;
    $('#model-alert-title').textContent = !online ? 'Local runtime disconnected' : 'No local model installed';
    $('#model-alert-text').textContent = !online
      ? 'The private Ollama runtime is unavailable. Reconnect it without closing MatrixStudio2.0.'
      : 'MatrixStudio2.0 is online, but chat needs a model in this project’s private model store.';
    $('#messages').classList.toggle('has-alert', !ready);
    $('#send-chat').disabled = !ready || !!state.abort;
    if (!state.abort && !['starting','thinking','generating'].includes(state.generationPhase)) {
      if (!online) setComposeStatus('Runtime disconnected · reconnect available');
      else if (!ready) setComposeStatus('Install a local model to start chatting');
    }
  }


  function closeSessionMenus(exceptButton=null) {
    const active = state.sessionMenu;
    if (!active || (exceptButton && active.button === exceptButton)) return;
    try { active.button?.setAttribute('aria-expanded', 'false'); } catch {}
    try { active.menu?.remove(); } catch {}
    state.sessionMenu = null;
  }

  function positionSessionMenu(menu, button) {
    const margin = 8;
    const br = button.getBoundingClientRect();
    menu.style.visibility = 'hidden';
    menu.style.left = '0px';
    menu.style.top = '0px';
    document.body.append(menu);
    const mr = menu.getBoundingClientRect();
    const width = Math.max(112, mr.width || 112);
    const height = Math.max(1, mr.height || 1);
    let left = br.right - width;
    left = clamp(left, margin, Math.max(margin, window.innerWidth - width - margin));
    const below = br.bottom + 6;
    const above = br.top - height - 6;
    let top = below;
    if (below + height > window.innerHeight - margin && above >= margin) top = above;
    top = clamp(top, margin, Math.max(margin, window.innerHeight - height - margin));
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
    menu.style.visibility = '';
  }

  function openSessionMenu(meta, button) {
    closeSessionMenus();
    const menu = document.createElement('div');
    menu.className = 'session-menu floating-session-menu';
    menu.setAttribute('role', 'menu');

    const pin = document.createElement('button');
    pin.type = 'button'; pin.setAttribute('role', 'menuitem'); pin.textContent = meta.pinned ? 'Unpin' : 'Pin';
    pin.addEventListener('click', async e => { e.stopPropagation(); closeSessionMenus(); await patchSession(meta.id, {pinned:!meta.pinned}); });

    const rename = document.createElement('button');
    rename.type = 'button'; rename.setAttribute('role', 'menuitem'); rename.textContent = 'Rename';
    rename.addEventListener('click', async e => { e.stopPropagation(); closeSessionMenus(); await renameSession(meta); });

    const exportBtn = document.createElement('button');
    exportBtn.type = 'button'; exportBtn.setAttribute('role', 'menuitem'); exportBtn.textContent = 'Export chat';
    exportBtn.addEventListener('click', async e => { e.stopPropagation(); closeSessionMenus(); await exportSessionById(meta.id); });

    const divider = document.createElement('div'); divider.className = 'session-menu-divider';
    const del = document.createElement('button');
    del.type = 'button'; del.setAttribute('role', 'menuitem'); del.className = 'danger'; del.textContent = 'Delete';
    del.addEventListener('click', async e => { e.stopPropagation(); closeSessionMenus(); await deleteSession(meta.id); });

    menu.append(pin, rename, exportBtn, divider, del);
    button.setAttribute('aria-expanded', 'true');
    state.sessionMenu = {menu, button, sessionId:meta.id};
    positionSessionMenu(menu, button);
    requestAnimationFrame(() => menu.querySelector('button')?.focus({preventScroll:true}));
  }


  function renderSessions() {
    closeSessionMenus();
    const list = $('#session-list'); list.replaceChildren();
    const q = state.search.trim().toLowerCase();
    const activeDraft = String($('#chat-input')?.value || '').trim();
    const visible = state.sessions.filter(s => Number(s.message_count || 0) > 0 || !!String(s.id === state.session?.id ? activeDraft : draftForSession(s.id)).trim());
    const rows = visible.filter(s => !q || `${s.title || ''} ${s.preview || ''} ${draftForSession(s.id)}`.toLowerCase().includes(q));
    const activeChanged = !!state.lastRenderedSessionId && state.lastRenderedSessionId !== state.session?.id;
    if (!rows.length) {
      const empty = document.createElement('div'); empty.className = 'session-empty';
      empty.textContent = q ? 'No conversations match that search.' : 'No conversations yet.';
      list.append(empty); state.lastRenderedSessionId = state.session?.id || ''; return;
    }

    const addLabel = (text) => {
      const label = document.createElement('div'); label.className = 'session-group-label'; label.textContent = text; list.append(label);
    };
    const pinnedRows = rows.filter(s => !!s.pinned);
    const recentRows = rows.filter(s => !s.pinned);
    const groups = q ? [[null, rows]] : [[pinnedRows.length ? 'PINNED' : null, pinnedRows], [pinnedRows.length && recentRows.length ? 'RECENT' : null, recentRows]];

    for (const [label, groupRows] of groups) {
      if (!groupRows.length) continue;
      if (label) addLabel(label);
      for (const s of groupRows) {
        const row = document.createElement('div');
        const active = state.session?.id === s.id;
        row.className = `session-item ${active ? 'active' : ''}${active && activeChanged ? ' selection-entering' : ''}${s.pinned ? ' pinned' : ''}`;
        row.dataset.id = s.id; row.tabIndex = 0;
        const copy = document.createElement('div'); copy.className = 'session-copy';
        const title = document.createElement('strong'); title.textContent = s.title || 'Chat';
        const meta = document.createElement('span'); meta.textContent = `${s.message_count || 0} msgs · ${fmtTime(s.updated_at)}`;
        copy.append(title, meta);

        const actions = document.createElement('div'); actions.className = 'session-actions';
        const more = document.createElement('div'); more.className = 'session-more';
        const moreButton = document.createElement('button');
        moreButton.className = 'session-more-button'; moreButton.type = 'button'; moreButton.title = 'Chat actions';
        moreButton.setAttribute('aria-label', `Actions for ${s.title || 'chat'}`);
        moreButton.setAttribute('aria-haspopup', 'menu'); moreButton.setAttribute('aria-expanded', 'false');
        moreButton.innerHTML = '<span></span><span></span><span></span>';
        moreButton.addEventListener('click', e => {
          e.stopPropagation();
          const alreadyOpen = state.sessionMenu?.button === moreButton;
          if (alreadyOpen) closeSessionMenus(); else openSessionMenu(s, moreButton);
        });
        more.append(moreButton); actions.append(more);
        row.append(copy, actions);
        row.addEventListener('click', e => { if (!e.target.closest('.session-actions')) loadSession(s.id); });
        row.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && !e.target.closest('.session-actions')) { e.preventDefault(); loadSession(s.id); } });
        list.append(row);
      }
    }
    state.lastRenderedSessionId = state.session?.id || '';
  }


  async function patchSession(id, patch) {
    const data = await api(`/api/sessions/${encodeURIComponent(id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(patch)});
    if (state.session?.id === id) state.session = data.session;
    await refreshSessions();
    if (state.session?.id === id) renderChat('keep');
  }

  async function renameSession(meta) {
    const next = window.prompt('Rename conversation', meta.title || '');
    if (next == null) return;
    const title = next.trim();
    if (!title || title === meta.title) return;
    await patchSession(meta.id, {title});
    setComposeStatus('Conversation renamed');
  }

  function createThinkingPanel(text = '', { open = false, live = false } = {}) {
    const panel = document.createElement('section');
    panel.className = `thinking-panel${open ? ' is-open' : ''}${live ? ' is-live' : ''}`;
    panel.hidden = !text && !live;

    const toggle = document.createElement('button');
    toggle.className = 'thinking-toggle'; toggle.type = 'button';
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');

    const title = document.createElement('span'); title.className = 'thinking-title';
    const dot = document.createElement('i');
    const titleText = document.createElement('span'); titleText.textContent = 'MODEL THINK';
    title.append(dot, titleText);

    const meta = document.createElement('span'); meta.className = 'thinking-meta';
    const chevron = document.createElement('span'); chevron.className = 'thinking-chevron'; chevron.textContent = '⌄';
    toggle.append(title, meta, chevron);

    const body = document.createElement('div'); body.className = 'thinking-body';
    const pre = document.createElement('pre'); pre.textContent = text; body.append(pre);
    panel.append(toggle, body);

    let modeLabel = '';
    let isLive = !!live;
    let isQuiet = false;
    const refreshMeta = () => {
      if (isQuiet) meta.textContent = modeLabel ? `${modeLabel} · No trace` : 'No trace';
      else if (isLive) meta.textContent = modeLabel ? `${modeLabel} · Thinking…` : 'Thinking…';
      else if (pre.textContent) meta.textContent = modeLabel ? `${modeLabel} · Trace available` : 'Reasoning available';
      else meta.textContent = modeLabel || 'Reasoning available';
    };
    const setOpen = (value) => {
      panel.classList.toggle('is-open', !!value);
      toggle.setAttribute('aria-expanded', value ? 'true' : 'false');
    };
    const setLive = (value) => {
      isLive = !!value;
      panel.classList.toggle('is-live', isLive);
      refreshMeta();
    };
    const setQuiet = (value) => {
      isQuiet = !!value;
      panel.classList.toggle('is-quiet', isQuiet);
      refreshMeta();
    };
    const setMode = (requested, effective) => {
      const req = String(requested || 'auto').toLowerCase();
      const eff = String(effective || req || 'direct').toLowerCase();
      modeLabel = req === 'auto' ? `AUTO → ${eff.toUpperCase()}` : (eff === 'deep' ? 'DEEP REASONING' : eff === 'standard' ? 'STANDARD THINK' : eff.toUpperCase());
      refreshMeta();
    };
    const setText = (value) => {
      pre.textContent = value || '';
      panel.hidden = !value && !isLive && !modeLabel;
      refreshMeta();
    };
    toggle.addEventListener('click', () => setOpen(!panel.classList.contains('is-open')));
    refreshMeta();
    return { panel, pre, meta, setOpen, setLive, setQuiet, setMode, setText };
  }

  function previousUserIndex(messages, fromIndex) {
    for (let i = Math.min(fromIndex, messages.length - 1); i >= 0; i--) if (messages[i]?.role === 'user') return i;
    return -1;
  }

  function messageRow(msg, animate = false, index = -1, messages = []) {
    const row = document.createElement('article'); row.className = `message-row ${msg.role}${animate ? ' entering' : ''}`;
    row.dataset.index = String(index);
    const label = document.createElement('div'); label.className = 'message-label';
    const who = document.createElement('span'); who.textContent = msg.role === 'user' ? 'YOU' : 'LOCAL MODEL';
    const right = document.createElement('span'); right.className = 'message-label-actions';

    if (msg.role === 'assistant') {
      const context = document.createElement('span'); context.className = `message-context${state.settings.show_message_model ? ' always' : ''}`;
      const model = msg.stats?.model || 'model unknown';
      const requested = String(msg.reasoning_mode || 'auto').toLowerCase();
      const effective = String(msg.effective_reasoning_mode || (requested === 'auto' ? 'model-default' : requested)).toLowerCase();
      const reasoning = requested === 'auto' ? `AUTO → ${effective.toUpperCase()}` : (effective === 'deep' ? 'DEEP REASONING' : effective === 'standard' ? 'STANDARD THINK' : effective.toUpperCase());
      context.textContent = `${model} · ${reasoning}`;
      right.append(context);
    }

    if (msg.role === 'user') {
      const edit = document.createElement('button'); edit.className = 'message-action'; edit.type = 'button'; edit.textContent = 'EDIT'; edit.title = 'Edit and resend from here';
      edit.addEventListener('click', () => beginInlineEdit(row, msg, index));
      right.append(edit);
      const hasAssistantAfter = messages.slice(index + 1).some(m => m?.role === 'assistant');
      if (!hasAssistantAfter) {
        const retry = document.createElement('button'); retry.className = 'message-action'; retry.type = 'button'; retry.textContent = 'RETRY'; retry.addEventListener('click', () => retryUserMessage(index));
        right.append(retry);
      }
    } else if (index === messages.length - 1) {
      const userIndex = previousUserIndex(messages, index - 1);
      if (userIndex >= 0) {
        const retry = document.createElement('button'); retry.className = 'message-action'; retry.type = 'button'; retry.textContent = 'RETRY'; retry.title = 'Regenerate the latest response';
        retry.addEventListener('click', () => retryUserMessage(userIndex));
        right.append(retry);
      }
    }

    if (msg.role === 'assistant' && state.settings.voice_output_enabled) {
      const speak = document.createElement('button'); speak.className = 'message-action'; speak.type = 'button'; speak.textContent = 'SPEAK'; speak.title = 'Speak this reply';
      speak.addEventListener('click', () => speakText(msg.content || '', {button:speak}).catch(e => showToast(e.message || 'Voice failed', {title:'Voice', tone:'danger', duration:3200})));
      right.append(speak);
    }

    const copy = document.createElement('button'); copy.className = 'copy-btn'; copy.type = 'button'; copy.textContent = 'COPY';
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(msg.content || ''); copy.textContent = 'COPIED'; setTimeout(() => copy.textContent = 'COPY', 900); } catch {}
    });
    right.append(copy); label.append(who, right); row.append(label);

    if (msg.role === 'assistant' && state.settings.show_model_thinking) {
      const requested = String(msg.reasoning_mode || 'auto').toLowerCase();
      const effective = String(msg.effective_reasoning_mode || (requested === 'auto' ? 'model-default' : requested)).toLowerCase();
      const routeNote = effective === 'direct'
        ? 'AUTO selected Direct for this turn; no extended reasoning was requested.'
        : 'No separate thinking trace was returned by this model for this turn.';
      const isDirect = effective === 'direct';
      const hasThinkingTrace = !isDirect && !!String(msg.thinking || '').trim();
      const thinkingText = hasThinkingTrace ? String(msg.thinking || '') : routeNote;
      const thinking = createThinkingPanel(thinkingText, { open:false, live:false });
      thinking.setMode(requested, effective);
      thinking.setQuiet(!hasThinkingTrace);
      row.append(thinking.panel);
    }

    const card = document.createElement('div'); card.className = 'message-card'; card.textContent = msg.content || '';
    row.append(card);
    if (msg.stats && state.settings.show_generation_stats) {
      const st = document.createElement('div'); st.className = 'message-stats'; st.textContent = statsText(msg.stats); row.append(st);
    }
    return row;
  }

  function beginInlineEdit(row, msg, index) {
    if (state.abort || msg.role !== 'user') return;
    const card = row.querySelector('.message-card');
    if (!card || card.querySelector('textarea')) return;
    const original = msg.content || '';
    card.replaceChildren(); card.classList.add('editing');
    const textarea = document.createElement('textarea'); textarea.className = 'message-edit-input'; textarea.value = original; textarea.rows = Math.min(8, Math.max(2, original.split('\n').length));
    const actions = document.createElement('div'); actions.className = 'message-edit-actions';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'message-action'; cancel.textContent = 'CANCEL';
    const send = document.createElement('button'); send.type = 'button'; send.className = 'message-action primary'; send.textContent = 'SAVE + RESEND';
    const restore = () => { card.classList.remove('editing'); card.replaceChildren(document.createTextNode(original)); };
    cancel.addEventListener('click', restore);
    send.addEventListener('click', async () => {
      const value = textarea.value.trim(); if (!value) return;
      if (index < (state.session?.messages?.length || 0) - 1 && !confirm('Edit from this point? Later messages in this conversation will be replaced.')) return;
      await editUserMessage(index, value);
    });
    textarea.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); restore(); }
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); send.click(); }
    });
    actions.append(cancel, send); card.append(textarea, actions); textarea.focus(); textarea.select();
  }

  function buildHero() {
    const wrap = document.createElement('div'); wrap.className = 'empty-state'; wrap.id = 'empty-state';
    wrap.innerHTML = `
      <div class="hero">
        <div class="hero-atmosphere" aria-hidden="true"><span></span><span></span><span></span></div>
        <div class="hero-orbit" aria-hidden="true"><span class="orbit-dot"></span><span class="orbit-dot small"></span><div class="hero-core"><span>M</span><sup>2</sup></div></div>
        <div class="hero-kicker">PRIVATE LOCAL INTELLIGENCE</div>
        <h1><span class="hero-line primary">Think clearly.</span><span class="hero-line secondary">Create freely.</span></h1>
        <p class="hero-copy">Private. Local. Ready when you are.</p>
        <div class="hero-menu">
          <div class="hero-menu-trace" aria-hidden="true"></div>
          <div class="hero-menu-head"><span>START HERE</span><span>Pick a direction</span></div>
          <div class="starter-grid">
            <button class="starter-card" type="button" data-prompt="Help me build something from a rough idea. Ask only what you need, then give me the strongest first version."><span class="starter-icon">↗</span><strong>Build</strong><span>Turn an idea into a strong first pass.</span></button>
            <button class="starter-card" type="button" data-prompt="Teach me a topic from the ground up. Start with the core idea, then build the details logically."><span class="starter-icon">◎</span><strong>Explore</strong><span>Break it down. Keep what matters.</span></button>
            <button class="starter-card" type="button" data-prompt="Help me improve some writing. Preserve my meaning, remove weak wording, and make it clearer."><span class="starter-icon">✎</span><strong>Write</strong><span>Make rough words clean and sharp.</span></button>
            <button class="starter-card" type="button" data-prompt="Help me solve a difficult problem. Identify the constraints, test the weak assumptions, then give me the strongest practical answer."><span class="starter-icon">◇</span><strong>Solve</strong><span>Find the clean path through the problem.</span></button>
          </div>
          <div class="hero-shortcuts" aria-hidden="true"><span><kbd>ENTER</kbd> Send</span><span><kbd>SHIFT + ENTER</kbd> New line</span><span><kbd>CTRL + N</kbd> New chat</span></div>
        </div>
      </div>`;
    wrap.querySelectorAll('.starter-card').forEach(btn => btn.addEventListener('click', () => {
      const input = $('#chat-input'); input.value = btn.dataset.prompt || ''; autoSizeInput(); input.focus();
    }));
    return wrap;
  }

  async function animateHeroExit() {
    const hero = $('#empty-state');
    if (!hero || document.body.classList.contains('reduce-motion')) return;
    state.heroExitActive = true;
    hero.classList.remove('hero-exiting');
    void hero.offsetWidth;
    hero.classList.add('hero-exiting');
    document.body.classList.add('chat-transitioning');
    setComposeStatus('Opening conversation…');
    await new Promise(resolve => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      hero.addEventListener('animationend', e => {
        if (e.target === hero && e.animationName === 'hero-exit-shell') done();
      }, {once:false});
      setTimeout(done, 460);
    });
    document.body.classList.remove('chat-transitioning');
    state.heroExitActive = false;
  }

  function renderChat(scrollMode = 'bottom') {
    const box = $('#messages');
    const previousScroll = box.scrollTop;
    const currentId = state.session?.id || '';
    const sessionChanged = !!state.lastChatSessionId && state.lastChatSessionId !== currentId;
    box.replaceChildren();
    const msgs = state.session?.messages || [];
    if (!msgs.length) box.append(buildHero());
    else msgs.forEach((m, i) => box.append(messageRow(m, false, i, msgs)));
    $('#chat-title').textContent = state.session?.title || 'New chat';
    const profile = sessionGenerationProfile();
    const reason = thinkModeInfo(profile.think_mode).label;
    $('#chat-meta').textContent = state.runtime.model_ready ? `${profile.model || 'Local model'} · ${reason}${profile.locked ? ' · LOCKED' : ''}` : 'No model installed';
    $('#message-count').textContent = `${msgs.length} message${msgs.length === 1 ? '' : 's'}`;
    syncSessionGenerationControls();
    if (sessionChanged) {
      box.classList.remove('session-swapped');
      requestAnimationFrame(() => { box.classList.add('session-swapped'); setTimeout(() => box.classList.remove('session-swapped'), 260); });
    }
    state.lastChatSessionId = currentId;
    requestAnimationFrame(() => {
      if (scrollMode === 'restore') {
        const saved = savedScrollForSession(currentId);
        box.scrollTop = saved == null ? box.scrollHeight : Math.min(saved, Math.max(0, box.scrollHeight - box.clientHeight));
      } else if (scrollMode === 'keep') {
        box.scrollTop = Math.min(previousScroll, Math.max(0, box.scrollHeight - box.clientHeight));
      } else box.scrollTop = box.scrollHeight;
    });
    renderSessions();
  }

  async function refreshSessions() {
    const data = await api('/api/sessions'); state.sessions = data.sessions || []; renderSessions();
  }

  async function createSession() {
    closeControlMenu();
    stopChat(false); persistCurrentSessionView(0);
    const currentIsEmpty = !!state.session && !(state.session.messages || []).length && !String($('#chat-input')?.value || '').trim();
    if (currentIsEmpty) { renderChat('keep'); $('#chat-input').focus(); return; }
    const data = await api('/api/sessions', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:'New chat'}) });
    state.session = data.session;
    $('#chat-input').value = ''; autoSizeInput();
    const drafts = {...(state.uiState?.session_drafts || {}), [state.session.id]:''};
    state.uiState = {...state.uiState, active_session_id:state.session.id, draft:'', session_drafts:drafts};
    persistUiState({active_session_id: state.session.id, draft:'', session_drafts:drafts}, 0);
    await refreshSessions(); renderChat('bottom'); $('#chat-input').focus();
  }

  async function loadSession(id) {
    if (state.session?.id === id) return;
    closeControlMenu();
    stopChat(false); persistCurrentSessionView(0);
    try {
      const data = await api(`/api/sessions/${encodeURIComponent(id)}`); state.session = data.session;
      const draft = draftForSession(id); $('#chat-input').value = draft; autoSizeInput();
      persistUiState({active_session_id: state.session.id, draft}, 0); renderChat('restore');
    } catch (e) { setComposeStatus(e.message); }
  }

  async function deleteSession(id) {
    if (state.settings.confirm_delete_chat !== false && !confirm('Delete this local chat? You can undo immediately after.')) return;
    const deletedMeta = state.sessions.find(s => s.id === id);
    const data = await api(`/api/sessions/${encodeURIComponent(id)}`, {method:'DELETE'});
    if (!data?.ok) return;
    const drafts = {...(state.uiState?.session_drafts || {})}; delete drafts[id];
    const scrolls = {...(state.uiState?.session_scroll || {})}; delete scrolls[id];
    state.uiState = {...state.uiState, session_drafts:drafts, session_scroll:scrolls};
    if (state.session?.id === id) { state.session = null; persistUiState({active_session_id:'', session_drafts:drafts, session_scroll:scrolls}, 0); }
    else persistUiState({session_drafts:drafts, session_scroll:scrolls}, 0);
    await refreshSessions();
    if (!state.session && state.sessions[0]) await loadSession(state.sessions[0].id);
    else if (!state.session) await createSession();

    if (data.trash_id) showToast(`“${deletedMeta?.title || 'Chat'}”`, {title:'Deleted', tone:'danger', label:'UNDO', action:async () => {
      const restored = await api('/api/sessions/restore', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({trash_id:data.trash_id})});
      await refreshSessions();
      if (restored?.session?.id) await loadSession(restored.session.id);
      showToast('Conversation restored', {tone:'success', duration:2200});
    }});
  }


  function appendStreamingAssistant() {
    const box = $('#messages'); $('#empty-state')?.remove();
    const row = document.createElement('article'); row.className = 'message-row assistant streaming entering'; row.id = 'stream-row';
    const label = document.createElement('div'); label.className = 'message-label';
    const who = document.createElement('span'); who.textContent = 'LOCAL MODEL';
    const live = document.createElement('span'); live.className = 'message-model live-model'; live.textContent = 'CONNECTING';
    label.append(who, live);

    const think = createThinkingPanel('', { open:true, live:true });
    think.panel.hidden = true;
    const card = document.createElement('div'); card.className = 'message-card streaming-cursor'; card.hidden = true;
    row.append(label, think.panel, card); box.append(row); box.scrollTop = box.scrollHeight;
    return { row, card, live, think, hasContent:false, hasThinking:false, reasoningExpected:false, effectiveReasoning:'direct' };
  }

  function setBusy(on) {
    $('#send-chat').hidden = on; $('#stop-chat').hidden = !on;
    $('#chat-input').disabled = on;
    if (!on) $('#send-chat').disabled = !state.runtime.model_ready;
    syncQuickControlLabels();
  }

  function stopChat(showStatus = true) {
    if (state.abort) state.abort.abort();
    state.abort = null; setBusy(false);
    if (showStatus) setGenerationPhase('stopped','Stopped');
    $('#stream-row')?.querySelector('.streaming-cursor')?.classList.remove('streaming-cursor');
  }

  function autoSizeInput() {
    const el = $('#chat-input'); el.style.height = 'auto'; el.style.height = `${clamp(el.scrollHeight, 36, 132)}px`;
  }

  function showTurnError(stream, message, retryIndex = null) {
    stream.row.classList.add('error');
    stream.card.hidden = false; stream.card.classList.remove('streaming-cursor'); stream.card.replaceChildren();
    const copy = document.createElement('div'); copy.className = 'turn-error-copy'; copy.textContent = message || 'The response could not be completed.';
    stream.card.append(copy);
    if (Number.isInteger(retryIndex) && retryIndex >= 0) {
      const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'message-action primary turn-retry'; retry.textContent = 'RETRY RESPONSE'; retry.addEventListener('click', () => retryUserMessage(retryIndex));
      stream.card.append(retry);
    }
  }

  async function consumeTurnStream(response, stream, retryIndex) {
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
    let assistant = '', thinking = '', accepted = false, streamError = null;
    while (true) {
      const {value, done} = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
      const lines = buffer.split('\n'); buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === 'meta') {
          accepted = true; state.session.id = ev.session_id; state.session.title = ev.title || state.session.title;
          persistUiState({active_session_id:state.session.id}, 0);
          stream.live.textContent = ev.model || 'STREAMING'; $('#chat-title').textContent = state.session.title;
          state.runtime = {...state.runtime, ok:true, state:'online', busy:true, model_ready:true, selected_model:ev.model || state.runtime.selected_model, active_generations:1}; renderRuntime();
          const requested = ev.reasoning_mode || state.settings.think_mode || 'auto';
          const effective = ev.effective_reasoning_mode || requested;
          stream.effectiveReasoning = String(effective).toLowerCase();
          stream.think.setMode(requested, effective);
          const showReasoning = state.settings.show_model_thinking !== false;
          stream.reasoningExpected = showReasoning && String(effective).toLowerCase() !== 'direct';
          setGenerationPhase(String(effective).toLowerCase() === 'direct' ? 'generating' : 'thinking', String(effective).toLowerCase() === 'direct' ? 'Generating…' : 'Thinking…');
          if (showReasoning) {
            stream.think.panel.hidden = false;
            if (stream.reasoningExpected) {
              stream.think.setQuiet(false);
              stream.think.setLive(true); stream.think.setOpen(true);
            } else {
              stream.think.setLive(false); stream.think.setOpen(false); stream.think.setQuiet(true);
              stream.think.setText('AUTO selected Direct for this turn; no extended reasoning was requested.');
            }
          }
        } else if (ev.type === 'content') {
          assistant += ev.text || ''; setGenerationPhase('generating', 'Generating…');
          if (!stream.hasContent) {
            stream.hasContent = true; stream.card.hidden = false;
            if (stream.hasThinking || stream.reasoningExpected) { stream.think.setLive(false); stream.think.setOpen(false); }
          }
          stream.card.textContent = assistant; $('#messages').scrollTop = $('#messages').scrollHeight;
        } else if (ev.type === 'think') {
          setGenerationPhase('thinking', 'Thinking…');
          // A resolved Direct turn must stay direct even if an older/odd runtime
          // emits an unexpected thinking field. Standard/Deep traces are unchanged.
          if (stream.effectiveReasoning === 'direct') continue;
          thinking += ev.text || '';
          if (!stream.hasThinking) { stream.hasThinking = true; stream.think.panel.hidden = false; stream.think.setQuiet(false); stream.think.setLive(true); stream.think.setOpen(true); }
          stream.think.setText(thinking); $('#messages').scrollTop = $('#messages').scrollHeight;
        } else if (ev.type === 'done') {
          setGenerationPhase('ready', 'Ready');
          if (stream.hasThinking || stream.reasoningExpected) {
            stream.think.setLive(false); stream.think.setOpen(false);
            if (stream.reasoningExpected && !stream.hasThinking) {
              stream.think.setQuiet(true);
              stream.think.setText('No separate thinking trace was returned by this model for this turn.');
            }
          }
        } else if (ev.type === 'error') {
          streamError = new Error(ev.error || 'Generation failed'); streamError.code = ev.code; streamError.retryable = ev.retryable !== false; break;
        }
      }
      if (streamError || done) break;
    }
    if (streamError) { streamError.accepted = accepted; throw streamError; }
    return {accepted, assistant, thinking};
  }

  async function ensureRuntimeReady() {
    if (state.runtime.ok && state.runtime.model_ready) return true;
    if (!state.runtime.ok) {
      const ok = await reconnectRuntime({silent:true});
      if (!ok) return false;
    }
    if (!state.runtime.model_ready) {
      setComposeStatus('Install a local model first'); $('#model-alert').hidden = false; return false;
    }
    return true;
  }

  async function runTurn(endpoint, payload, retryIndex, {onRejected=null, suppressAutoSpeak=false} = {}) {
    if (state.abort) return false;
    if (!(await ensureRuntimeReady())) return false;
    const stream = appendStreamingAssistant();
    const abort = new AbortController(); state.abort = abort; setBusy(true); setGenerationPhase('starting', 'Starting…');
    try {
      const r = await fetch(endpoint, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload), signal:abort.signal});
      if (!r.ok) {
        let detail = `${r.status} ${r.statusText}`; try { detail = (await r.json()).detail || detail; } catch {}
        const err = new Error(detail); err.status = r.status; throw err;
      }
      const completedTurn = await consumeTurnStream(r, stream, retryIndex);
      stream.card.classList.remove('streaming-cursor');
      await refreshSessions();
      const current = await api(`/api/sessions/${encodeURIComponent(state.session.id)}`); state.session = current.session; renderChat('bottom');
      setGenerationPhase('ready', 'Ready'); await refreshRuntime({silent:true}).catch(()=>{});
      if (!suppressAutoSpeak && state.settings.voice_output_enabled && state.settings.tts_auto_speak && completedTurn?.assistant) void speakText(completedTurn.assistant).catch(e => setComposeStatus(`Voice · ${e.message}`));
      return completedTurn;
    } catch (e) {
      stream.card.classList.remove('streaming-cursor');
      if (e.name === 'AbortError') {
        stream.think.setLive(false); stream.think.setOpen(false); showTurnError(stream, 'Generation stopped. The prompt is still saved.', retryIndex); setGenerationPhase('stopped','Stopped');
      } else if (e.status && onRejected) {
        stream.row.remove(); await onRejected(e); setComposeStatus(`Chat blocked · ${e.message}`);
        if (e.status === 409 || e.status === 503) { await refreshRuntime().catch(()=>{}); $('#model-alert').hidden = false; }
      } else {
        stream.think.setLive(false); stream.think.setOpen(false); showTurnError(stream, e.message || 'The local model could not finish this response.', retryIndex);
        setGenerationPhase('error','Response failed · retry available'); await refreshSessions().catch(()=>{}); await refreshRuntime({silent:true}).catch(()=>{});
      }
      return null;
    } finally {
      state.abort = null; setBusy(false); $('#chat-input').disabled = false; $('#chat-input').focus();
      if (state.generationPhase === 'starting' || state.generationPhase === 'thinking' || state.generationPhase === 'generating') setGenerationPhase('ready','Ready');
    }
  }

  async function sendChat(forcedText = null, {suppressAutoSpeak=false} = {}) {
    if (state.abort || state.heroExitActive) return null;
    const input = $('#chat-input'); const text = forcedText === null ? input.value.trim() : String(forcedText || '').trim(); if (!text) return null;
    if (!(await ensureRuntimeReady())) return;
    if (!state.session) await createSession();
    if (!(state.session.messages || []).length && $('#empty-state')) await animateHeroExit();
    const userIndex = state.session.messages.length;
    const localUser = {role:'user', content:text}; state.session.messages.push(localUser);
    if (forcedText === null) {
      input.value = ''; autoSizeInput();
      const drafts = {...(state.uiState?.session_drafts || {}), [state.session.id]:''};
      state.uiState = {...state.uiState, draft:'', session_drafts:drafts}; persistUiState({draft:'', session_drafts:drafts}, 0);
    }
    renderChat('bottom'); $('#messages .message-row.user:last-of-type')?.classList.add('entering');
    return await runTurn('/api/chat', {session_id:state.session.id, message:text}, userIndex, {suppressAutoSpeak, onRejected:async () => {
      if (state.session?.messages?.at(-1) === localUser) state.session.messages.pop();
      input.value = text; autoSizeInput(); renderChat('bottom');
    }});
  }

  async function retryUserMessage(userIndex) {
    if (state.abort || !state.session?.id) return;
    if (!(await ensureRuntimeReady())) return;
    const original = state.session.messages?.[userIndex];
    if (!original || original.role !== 'user') return;
    state.session.messages = state.session.messages.slice(0, userIndex + 1);
    renderChat('bottom');
    await runTurn('/api/chat/retry', {session_id:state.session.id, message_index:userIndex}, userIndex, {onRejected:async () => {
      const current = await api(`/api/sessions/${encodeURIComponent(state.session.id)}`).catch(()=>null); if (current?.session) state.session=current.session; renderChat('bottom');
    }});
  }

  async function editUserMessage(userIndex, text) {
    if (state.abort || !state.session?.id) return;
    if (!(await ensureRuntimeReady())) return;
    const original = state.session.messages?.[userIndex];
    if (!original || original.role !== 'user') return;
    state.session.messages = state.session.messages.slice(0, userIndex + 1);
    state.session.messages[userIndex] = {...original, content:text}; renderChat('bottom');
    await runTurn('/api/chat/edit', {session_id:state.session.id, message_index:userIndex, message:text}, userIndex, {onRejected:async () => {
      const current = await api(`/api/sessions/${encodeURIComponent(state.session.id)}`).catch(()=>null); if (current?.session) state.session=current.session; renderChat('bottom');
    }});
  }

  function fillSettingsForm(resetDirty = true) {
    const s = state.settings;
    fillModelSelect($('#set-model'), state.runtime.models, s.ollama_chat_model);
    $('#set-context').value = String(s.ollama_num_ctx || 8192);
    $('#set-keepalive').value = s.ollama_keep_alive ?? '5m';
    $('#set-num-predict').value = s.ollama_num_predict ?? -1;
    $('#set-temperature').value = s.chat_temperature ?? 0.65; $('#temp-output').value = Number(s.chat_temperature ?? .65).toFixed(2);
    $('#set-history').value = s.history_turns ?? 12; $('#set-think').value = s.think_mode || 'auto';
    $('#set-show-thinking').checked = s.show_model_thinking !== false; $('#set-plain-chat').checked = !!s.plain_chat; $('#set-show-stats').checked = s.show_generation_stats !== false; $('#set-show-message-model').checked = !!s.show_message_model;
    $('#set-auto-title').checked = s.auto_title_chats !== false; $('#set-confirm-delete').checked = s.confirm_delete_chat !== false;
    $('#set-voice-output').checked = !!s.voice_output_enabled; $('#set-tts-provider').value = s.tts_provider || 'browser'; $('#set-tts-auto-speak').checked = !!s.tts_auto_speak; $('#set-tts-allow-online').checked = !!s.tts_allow_online;
    primeEdgeVoiceSelection(s.tts_edge_voice || 'en-US-AvaNeural'); $('#set-tts-local-voice').value = s.tts_local_voice || 'en_US-lessac-medium'; $('#set-tts-fallback').value = s.tts_online_fallback || 'browser';
    $('#set-tts-rate').value = s.tts_rate ?? 1; $('#tts-rate-output').value = Number(s.tts_rate ?? 1).toFixed(2); $('#set-tts-pitch').value = s.tts_pitch ?? 1; $('#tts-pitch-output').value = Number(s.tts_pitch ?? 1).toFixed(2);
    $('#set-tts-volume').value = s.tts_volume ?? 1; $('#tts-volume-output').value = Number(s.tts_volume ?? 1).toFixed(2); $('#set-tts-tone').value = s.tts_tone || 'neutral'; $('#set-tts-intensity').value = s.tts_intensity ?? .7; $('#tts-intensity-output').value = `${Math.round(Number(s.tts_intensity ?? .7) * 100)}%`; $('#set-tts-pause-style').value = s.tts_pause_style || 'natural';
    $('#set-tts-max-chars').value = s.tts_max_chars ?? TTS_HARD_CEILING; $('#set-tts-cpu-threads').value = s.tts_cpu_threads ?? 2; $('#set-tts-skip-code').checked = s.tts_skip_code !== false; $('#set-tts-skip-urls').checked = s.tts_skip_urls !== false; $('#set-tts-stop-previous').checked = s.tts_stop_previous !== false;
    $('#set-stt-browser-fallback').checked = !!s.stt_allow_browser_online; $('#set-stt-local-model').value = s.stt_local_model || 'base.en';
    syncTTSProviderUI();
    if ((s.tts_provider || 'browser') === 'edge' && !!s.tts_allow_online) setTimeout(() => { void loadEdgeVoices().catch(()=>{}); }, 0);
    $('#set-retrieval-enabled').checked = s.retrieval_enabled !== false; $('#set-retrieval-chat').checked = s.retrieval_include_older_chat !== false; $('#set-retrieval-cross-chat').checked = s.retrieval_include_cross_chat !== false; $('#set-retrieval-knowledge').checked = s.retrieval_include_knowledge !== false;
    $('#set-system-prompt').value = s.system_prompt || '';
    $('#set-ui-mode').value = s.ui_mode || 'dark'; $('#set-theme').value = s.theme_preset || 'matrix'; $('#set-density').value = s.ui_density || 'comfortable';
    $('#set-ui-scale').value = s.ui_font_scale || 1; $('#ui-scale-output').value = Number(s.ui_font_scale || 1).toFixed(2);
    $('#set-chat-scale').value = s.chat_font_scale || 1; $('#chat-scale-output').value = Number(s.chat_font_scale || 1).toFixed(2);
    $('#set-window-width').value = s.window_width || 1440; $('#set-window-height').value = s.window_height || 900; $('#set-reduce-motion').checked = !!s.reduce_motion;
    $('#set-gradients').value = s.gradients_enabled ? 'on' : 'off';
    $('#set-gradient-strength').value = s.gradient_strength ?? .42; $('#gradient-strength-output').value = Number(s.gradient_strength ?? .42).toFixed(2);
    $('#set-custom-colors').checked = !!s.custom_colors_enabled;
    const colorDefaults = {
      'set-accent-color': s.accent_color || '#66e2ba', 'set-accent-secondary': s.accent_secondary || '#24d49a',
      'set-background-color': s.background_color || '#07100d', 'set-panel-color': s.panel_color || '#0a1215',
      'set-user-bubble-color': s.user_bubble_color || '#15302a', 'set-assistant-bubble-color': s.assistant_bubble_color || '#111b22',
      'set-muted-text-color': s.muted_text_color || '#82969a'
    };
    for (const [id, value] of Object.entries(colorDefaults)) $('#'+id).value = value;
    $('#accent-color-value').textContent = colorDefaults['set-accent-color']; $('#accent-secondary-value').textContent = colorDefaults['set-accent-secondary'];
    $('#background-color-value').textContent = colorDefaults['set-background-color']; $('#panel-color-value').textContent = colorDefaults['set-panel-color'];
    $('#user-bubble-color-value').textContent = colorDefaults['set-user-bubble-color']; $('#assistant-bubble-color-value').textContent = colorDefaults['set-assistant-bubble-color'];
    $('#muted-text-color-value').textContent = colorDefaults['set-muted-text-color'];
    $('#set-background-opacity').value = s.background_image_opacity ?? .62; $('#background-opacity-output').value = Number(s.background_image_opacity ?? .62).toFixed(2);
    $('#set-background-blur').value = s.background_blur ?? 16; $('#background-blur-output').value = `${Number(s.background_blur ?? 16).toFixed(0)}px`;
    $('#set-background-dim').value = s.background_dim ?? .42; $('#background-dim-output').value = Number(s.background_dim ?? .42).toFixed(2);
    $('#set-panel-opacity').value = s.panel_opacity ?? .88; $('#panel-opacity-output').value = Number(s.panel_opacity ?? .88).toFixed(2);
    $('#set-panel-blur').value = s.panel_blur ?? 18; $('#panel-blur-output').value = `${Number(s.panel_blur ?? 18).toFixed(0)}px`;
    $('#set-glow-strength').value = s.glow_strength ?? .32; $('#glow-strength-output').value = Number(s.glow_strength ?? .32).toFixed(2);
    $('#background-status').textContent = s.background_image_enabled ? 'Custom image active' : 'No custom image';
    $('#remove-background').disabled = !s.background_image_enabled;
    if (!$('#pull-model').value) $('#pull-model').value = state.runtime.starter_model || 'llama3.2:3b';
    if (resetDirty) { $('#settings-status').textContent = 'No unsaved changes'; state.dirty = false; }
  }

  function collectSettings() {
    const chosen = $('#set-model').value || state.settings.ollama_chat_model || '';
    return {
      ollama_chat_model: chosen,
      ollama_num_ctx: Number($('#set-context').value), ollama_keep_alive: $('#set-keepalive').value.trim(), ollama_num_predict: Number($('#set-num-predict').value),
      chat_temperature: Number($('#set-temperature').value), history_turns: Number($('#set-history').value), think_mode: $('#set-think').value,
      show_model_thinking: $('#set-show-thinking').checked, plain_chat: $('#set-plain-chat').checked, show_generation_stats: $('#set-show-stats').checked, show_message_model: $('#set-show-message-model').checked,
      auto_title_chats: $('#set-auto-title').checked, confirm_delete_chat: $('#set-confirm-delete').checked,
      voice_output_enabled: $('#set-voice-output').checked, tts_provider: $('#set-tts-provider').value, tts_auto_speak: $('#set-tts-auto-speak').checked, tts_allow_online: $('#set-tts-allow-online').checked,
      tts_edge_voice: $('#set-tts-edge-voice').value.trim(), tts_local_voice: $('#set-tts-local-voice').value.trim(), tts_online_fallback: $('#set-tts-fallback').value,
      tts_rate: Number($('#set-tts-rate').value), tts_pitch: Number($('#set-tts-pitch').value), tts_volume: Number($('#set-tts-volume').value), tts_tone: $('#set-tts-tone').value, tts_intensity: Number($('#set-tts-intensity').value), tts_pause_style: $('#set-tts-pause-style').value, tts_max_chars: Number($('#set-tts-max-chars').value), tts_cpu_threads: Number($('#set-tts-cpu-threads').value),
      tts_skip_code: $('#set-tts-skip-code').checked, tts_skip_urls: $('#set-tts-skip-urls').checked, tts_stop_previous: $('#set-tts-stop-previous').checked,
      stt_provider: 'hybrid', stt_allow_browser_online: $('#set-stt-browser-fallback').checked, stt_local_model: $('#set-stt-local-model').value, stt_max_seconds: 60,
      retrieval_enabled: $('#set-retrieval-enabled').checked, retrieval_include_older_chat: $('#set-retrieval-chat').checked, retrieval_include_cross_chat: $('#set-retrieval-cross-chat').checked, retrieval_include_knowledge: $('#set-retrieval-knowledge').checked,
      retrieval_max_chunks: 4, retrieval_max_chars: 3600,
      system_prompt: $('#set-system-prompt').value, ui_mode: $('#set-ui-mode').value, theme_preset: $('#set-theme').value, ui_density: $('#set-density').value,
      ui_font_scale: Number($('#set-ui-scale').value), chat_font_scale: Number($('#set-chat-scale').value), window_width: Number($('#set-window-width').value),
      window_height: Number($('#set-window-height').value), reduce_motion: $('#set-reduce-motion').checked,
      background_fit: 'preserve', gradients_enabled: $('#set-gradients').value === 'on', gradient_strength: Number($('#set-gradient-strength').value),
      custom_colors_enabled: $('#set-custom-colors').checked, accent_color: $('#set-accent-color').value, accent_secondary: $('#set-accent-secondary').value,
      background_color: $('#set-background-color').value, panel_color: $('#set-panel-color').value, user_bubble_color: $('#set-user-bubble-color').value, assistant_bubble_color: $('#set-assistant-bubble-color').value, muted_text_color: $('#set-muted-text-color').value,
      background_image_opacity: Number($('#set-background-opacity').value), background_blur: Number($('#set-background-blur').value), background_dim: Number($('#set-background-dim').value),
      background_zoom: 100, panel_opacity: Number($('#set-panel-opacity').value), panel_blur: Number($('#set-panel-blur').value), glow_strength: Number($('#set-glow-strength').value)
    };
  }

  async function persistSettingsSnapshot(snapshot, {announce=false} = {}) {
    const seq = ++state.settingsSaveSeq;
    const data = await api('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(snapshot)});
    if (seq !== state.settingsSaveSeq) return data.settings || state.settings;
    state.settings = data.settings || {...state.settings, ...snapshot};
    state.dirty = false;
    $('#settings-status').textContent = announce ? 'Saved' : 'Saved automatically';
    if (announce) setComposeStatus('Settings saved');
    return state.settings;
  }

  function scheduleSettingsAutosave(delay = 100) {
    let snapshot;
    try { snapshot = collectSettings(); } catch { return; }
    state.settings = {...state.settings, ...snapshot};
    clearTimeout(state.settingsSaveTimer);
    state.settingsSaveTimer = setTimeout(() => {
      persistSettingsSnapshot(snapshot).catch(e => {
        state.dirty = true;
        $('#settings-status').textContent = `Autosave failed · ${e.message}`;
      });
    }, delay);
  }

  async function flushSettingsAutosave() {
    if (!state.dirty) return true;
    clearTimeout(state.settingsSaveTimer);
    state.settingsSaveTimer = null;
    try {
      await persistSettingsSnapshot(collectSettings());
      return true;
    } catch (e) {
      state.dirty = true;
      $('#settings-status').textContent = `Autosave failed · ${e.message}`;
      return false;
    }
  }

  function markDirty() {
    state.dirty = true;
    $('#settings-status').textContent = 'Saving…';
    scheduleSettingsAutosave();
  }

  async function saveSettings() {
    try {
      clearTimeout(state.settingsSaveTimer);
      state.settingsSaveTimer = null;
      const settings = await persistSettingsSnapshot(collectSettings(), {announce:true});
      persistUiState({window_width:Number(settings.window_width || innerWidth), window_height:Number(settings.window_height || innerHeight)}, 0);
      applyAppearance(settings);
      if (state.session?.id && !sessionControlsLocked()) {
        const patch = {model:settings.ollama_chat_model, think_mode:settings.think_mode || 'auto'};
        const data = await api(`/api/sessions/${encodeURIComponent(state.session.id)}/generation`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)}).catch(()=>null);
        if (data?.session) state.session = data.session;
      }
      syncSessionGenerationControls();
      renderChat('keep');
      fillSettingsForm(true);
      return true;
    } catch (e) { $('#settings-status').textContent = `Save failed · ${e.message}`; return false; }
  }

  async function quickPatch(patch) {
    try {
      const data = await api('/api/settings',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(patch)});
      const saved = data.settings || {};
      // Quick header controls are intentionally narrow patches. They must not
      // re-apply the full appearance payload because that would overwrite a
      // live Settings preview (or a draft the user has not saved yet).
      for (const key of Object.keys(patch)) {
        state.settings[key] = key in saved ? saved[key] : patch[key];
      }
      if ('think_mode' in patch) {
        $('#quick-think').value = state.settings.think_mode;
        $('#set-think').value = state.settings.think_mode;
      }
      if ('ollama_chat_model' in patch) {
        $('#quick-model').value = state.settings.ollama_chat_model;
        $('#set-model').value = state.settings.ollama_chat_model;
      }
      syncQuickControlLabels();
      if ('selected_specialist_id' in patch) await loadSpecialistGroups({quiet:true});
      renderChat('keep');
    } catch (e) { setComposeStatus(`Setting failed · ${e.message}`); }
  }

  async function patchSessionGeneration(patch) {
    if (!state.session?.id) return;
    if (sessionControlsLocked()) {
      setComposeStatus('This chat is already locked. Start a new chat to change model or reasoning.');
      syncSessionGenerationControls();
      return;
    }
    try {
      const data = await api(`/api/sessions/${encodeURIComponent(state.session.id)}/generation`, {
        method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(patch)
      });
      state.session = data.session || state.session;
      syncSessionGenerationControls();
      renderChat('keep');
      const label = 'model' in patch ? sessionGenerationProfile().model : thinkModeInfo(sessionGenerationProfile().think_mode).label;
      setComposeStatus(`New chat profile · ${label}`);
    } catch (e) {
      setComposeStatus(`Chat profile update failed · ${e.message}`);
      const current = await api(`/api/sessions/${encodeURIComponent(state.session.id)}`).catch(()=>null);
      if (current?.session) state.session = current.session;
      syncSessionGenerationControls();
    }
  }

  async function refreshRuntime({silent=false} = {}) {
    try {
      state.runtime = await api('/api/llm/status');
      if (state.runtime.model_ready && state.runtime.selected_model) state.settings.ollama_chat_model = state.runtime.selected_model;
      renderRuntime(); if (!state.dirty) fillSettingsForm(true); renderChat('keep');
      if (!silent && state.runtime.ok && state.runtime.model_ready && !state.abort) setComposeStatus('Ready');
      return state.runtime;
    } catch (e) { if (!silent) setComposeStatus(e.message); throw e; }
  }


  async function reconnectRuntime({silent=false} = {}) {
    const buttons = [$('#reconnect-runtime'), $('#model-alert-reconnect')].filter(Boolean);
    buttons.forEach(b => b.disabled = true);
    if (!silent) setComposeStatus('Reconnecting private runtime…');
    try {
      const data = await api('/api/runtime/reconnect', {method:'POST'});
      state.runtime = data.runtime || await api('/api/llm/status');
      if (state.runtime.model_ready && state.runtime.selected_model) state.settings.ollama_chat_model = state.runtime.selected_model;
      renderRuntime();
      if (!state.dirty) fillSettingsForm(true);
      renderChat('keep');
      if (!silent) setComposeStatus(data.started ? 'Runtime restarted · ready' : 'Runtime connected');
      return !!state.runtime.ok;
    } catch (e) {
      if (!silent) setComposeStatus(`Reconnect failed · ${e.message}`);
      await refreshRuntime().catch(()=>{});
      return false;
    } finally { buttons.forEach(b => b.disabled = false); }
  }

  function startRuntimeWatch() {
    clearInterval(state.runtimeWatchTimer);
    state.runtimeWatchTimer = setInterval(async () => {
      if (state.abort || document.hidden) return;
      try {
        const runtime = await api('/api/llm/status');
        const changed = runtime.state !== state.runtime.state || !!runtime.ok !== !!state.runtime.ok || !!runtime.model_ready !== !!state.runtime.model_ready || runtime.selected_model !== state.runtime.selected_model || JSON.stringify(runtime.loaded_models||[]) !== JSON.stringify(state.runtime.loaded_models||[]) || Number(runtime.loaded_vram_bytes||0) !== Number(state.runtime.loaded_vram_bytes||0);
        state.runtime = runtime;
        if (changed) { renderRuntime(); renderChat('keep'); }
      } catch {}
    }, 6500);
  }

  async function resetSection(section) {
    if (!confirm(section === 'all' ? 'Reset all MatrixStudio2.0 settings and remembered UI state? Chats and local models are kept.' : `Reset ${section} settings?`)) return;
    const data = await api('/api/settings/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section})});
    state.settings = data.settings || {};
    if (section === 'all') {
      state.uiState = data.ui_state || {};
      document.body.classList.remove('sidebar-collapsed','sidebar-open');
      $('#chat-input').value = ''; autoSizeInput();
    }
    if (section === 'appearance') persistUiState({window_width:Number(state.settings.window_width || 1440), window_height:Number(state.settings.window_height || 900)}, 0);
    if (section === 'specialists' || section === 'all') await loadSpecialistGroups({quiet:true});
    applyAppearance(); await refreshRuntime(); fillSettingsForm(); renderChat(); $('#quick-think').value = state.settings.think_mode;
  }

  async function startPull(modelOverride = '') {
    const model = String(modelOverride || $('#pull-model').value || '').trim(); if (!model) return;
    $('#pull-model').value = model;
    try {
      await api('/api/llm/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model})});
      $('#pull-progress').hidden = false; $('#pull-model-btn').disabled = true; $('#install-starter').disabled = true;
      setComposeStatus(`Installing ${model}…`); pollPull();
    } catch (e) {
      $('#pull-label').textContent = e.message; $('#pull-progress').hidden = false; setComposeStatus(e.message);
    }
  }

  async function pollPull() {
    clearTimeout(state.pullTimer);
    try {
      const p = await api('/api/llm/pull/status');
      $('#pull-progress').hidden = false; $('#pull-label').textContent = `${p.model || ''} · ${p.error || p.status || ''}`;
      const pct = p.total ? Math.round((p.completed / p.total) * 100) : 0; $('#pull-bar').value = pct;
      $('#pull-percent').textContent = p.total ? `${pct}% · ${fmtBytes(p.completed)} / ${fmtBytes(p.total)}` : '';
      if (p.running) state.pullTimer = setTimeout(pollPull, 700);
      else {
        $('#pull-model-btn').disabled = false; $('#install-starter').disabled = false;
        if (!p.error && p.model) {
          const data = await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ollama_chat_model:p.model})});
          state.settings = data.settings || state.settings;
          await refreshRuntime(); setComposeStatus(`Model ready · ${p.model}`); $('#settings-status').textContent = 'Model installed';
        } else setComposeStatus(`Model install failed · ${p.error || 'unknown error'}`);
      }
    } catch (e) { $('#pull-label').textContent = e.message; $('#pull-model-btn').disabled = false; $('#install-starter').disabled = false; }
  }

  function looksLikeHFRepo(value) {
    const text = String(value || '').trim();
    if (/^https:\/\/huggingface\.co\/[^/\s]+\/[^/?#\s]+/i.test(text)) return true;
    return /^[^/\s]+\/[^/\s]+$/.test(text);
  }

  function setHFStatus(text, tone = '') {
    const el = $('#hf-status');
    if (!el) return;
    el.textContent = text || '';
    el.dataset.tone = tone || '';
  }

  function renderHFSearchResults(rows = []) {
    const host = $('#hf-results');
    if (!host) return;
    host.replaceChildren();
    host.hidden = !rows.length;
    for (const row of rows) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'hf-result-card';
      const copy = document.createElement('div');
      const strong = document.createElement('strong'); strong.textContent = row.repo_id || 'Repository';
      const meta = document.createElement('span');
      meta.textContent = `${Number(row.downloads || 0).toLocaleString()} downloads · ${Number(row.likes || 0).toLocaleString()} likes`;
      copy.append(strong, meta);
      const action = document.createElement('em'); action.textContent = 'INSPECT';
      button.append(copy, action);
      button.addEventListener('click', () => inspectHFRepo(row.repo_id));
      host.append(button);
    }
  }

  function sortedHFGroups() {
    const rows = [...(state.hfGroups || [])];
    const mode = $('#hf-sort')?.value || 'largest-fit';
    if (mode === 'size') return rows.sort((a,b) => Number(a.total_bytes||0) - Number(b.total_bytes||0));
    if (mode === 'quant') return rows.sort((a,b) => String(a.quant||'').localeCompare(String(b.quant||'')) || Number(a.total_bytes||0)-Number(b.total_bytes||0));
    const rank = {likely:0,tight:1,partial:2,heavy:3};
    return rows.sort((a,b) => (rank[a.fit?.tier] ?? 9) - (rank[b.fit?.tier] ?? 9) || Number(b.total_bytes||0) - Number(a.total_bytes||0));
  }

  function selectHFGroup(groupId) {
    const group = (state.hfGroups || []).find(g => g.id === groupId && g.complete);
    if (!group) return;
    state.hfSelectedGroup = group.id;
    const input = $('#hf-local-name'); if (input) input.value = group.suggested_local_name || '';
    const install = $('#hf-install-btn'); if (install) install.disabled = false;
    renderHFGroups();
  }

  function renderHFGroups() {
    const host = $('#hf-quant-list');
    if (!host) return;
    host.replaceChildren();
    const rows = sortedHFGroups();
    if (!rows.length) {
      const empty = document.createElement('div'); empty.className = 'hf-empty'; empty.textContent = 'No GGUF choices found.'; host.append(empty); return;
    }
    for (const group of rows) {
      const button = document.createElement('button');
      button.type = 'button';
      const selected = group.id === state.hfSelectedGroup;
      button.className = `hf-quant-card${selected ? ' selected' : ''}${group.complete ? '' : ' incomplete'}`;
      button.disabled = !group.complete;
      const top = document.createElement('div'); top.className = 'hf-quant-top';
      const quant = document.createElement('strong'); quant.textContent = group.quant || 'UNKNOWN / CUSTOM';
      const fit = document.createElement('span'); fit.className = `hf-fit ${group.fit?.tier || 'heavy'}`; fit.textContent = group.fit?.label || 'VRAM UNKNOWN';
      top.append(quant, fit);
      const meta = document.createElement('div'); meta.className = 'hf-quant-meta';
      const shardText = Number(group.shard_count || 1) === 1 ? 'single GGUF' : `${group.shard_count} shards`;
      meta.textContent = `${fmtBytes(group.total_bytes)} · ${shardText}`;
      const detail = document.createElement('small');
      detail.textContent = group.complete ? (group.label || '') : `Incomplete split · missing shard${(group.missing_shards||[]).length===1?'':'s'} ${(group.missing_shards||[]).join(', ')}`;
      button.append(top, meta, detail);
      if (group.complete) button.addEventListener('click', () => selectHFGroup(group.id));
      host.append(button);
    }
  }

  async function inspectHFRepo(repoInput) {
    const repo = String(repoInput || $('#hf-search')?.value || '').trim();
    if (!repo) return;
    setHFStatus(`Inspecting ${repo}…`);
    $('#hf-search-btn').disabled = true;
    try {
      const data = await api(`/api/hf/repo?repo=${encodeURIComponent(repo)}`);
      state.hfRepo = data.repo || null;
      state.hfGroups = state.hfRepo?.groups || [];
      state.hfSelectedGroup = '';
      $('#hf-results').hidden = true;
      $('#hf-repo').hidden = !state.hfRepo;
      if (!state.hfRepo) throw new Error('Repository details were unavailable.');
      $('#hf-repo-name').textContent = state.hfRepo.repo_id;
      $('#hf-repo-meta').textContent = `${state.hfGroups.length} GGUF choice${state.hfGroups.length===1?'':'s'} · ${Number(state.hfRepo.downloads||0).toLocaleString()} downloads`;
      const first = sortedHFGroups().find(g => g.complete);
      if (first) {
        state.hfSelectedGroup = first.id;
        $('#hf-local-name').value = first.suggested_local_name || '';
        $('#hf-install-btn').disabled = false;
      } else {
        $('#hf-local-name').value = '';
        $('#hf-install-btn').disabled = true;
      }
      renderHFGroups();
      setHFStatus('Choose the exact quant you want. Larger options stay visible for RAM/CPU offload experiments.', 'ok');
    } catch (e) {
      state.hfRepo = null; state.hfGroups = []; state.hfSelectedGroup = '';
      $('#hf-repo').hidden = true; $('#hf-install-btn').disabled = true;
      setHFStatus(e.message, 'error');
    } finally { $('#hf-search-btn').disabled = false; }
  }

  async function searchHF() {
    const query = String($('#hf-search')?.value || '').trim();
    if (!query) { setHFStatus('Enter a search or public Hugging Face repository.', 'error'); return; }
    if (looksLikeHFRepo(query)) { await inspectHFRepo(query); return; }
    setHFStatus(`Searching Hugging Face for “${query}”…`);
    $('#hf-search-btn').disabled = true;
    try {
      const data = await api(`/api/hf/search?q=${encodeURIComponent(query)}&limit=12`);
      const rows = data.models || [];
      renderHFSearchResults(rows);
      $('#hf-repo').hidden = true;
      setHFStatus(rows.length ? `${rows.length} public GGUF repos found. Pick one to inspect.` : 'No public GGUF repositories matched that search.', rows.length ? 'ok' : '');
    } catch (e) {
      renderHFSearchResults([]); setHFStatus(e.message, 'error');
    } finally { $('#hf-search-btn').disabled = false; }
  }

  function renderHFInstallState(p = {}) {
    const panel = $('#hf-install-progress'); if (!panel) return;
    const active = !!p.running || !['idle', undefined, null].includes(p.phase);
    panel.hidden = !active;
    if (!active) return;
    const phaseNames = {
      preflight:'Preparing', downloading:'Downloading GGUF', verifying:'Verifying SHA-256', waiting_runtime:'Waiting for Ollama',
      registering:'Registering blobs', creating:'Creating Ollama model', ready:'Model ready', cancelled:'Cancelled', failed:'Install failed'
    };
    $('#hf-install-phase').textContent = phaseNames[p.phase] || p.status || 'Working…';
    $('#hf-install-detail').textContent = p.error || p.status || p.current_file || '';
    const pct = Number.isFinite(Number(p.percent)) ? Number(p.percent) : 0;
    $('#hf-install-bar').value = clamp(pct, 0, 100);
    $('#hf-install-bytes').textContent = p.total ? `${Math.round(pct)}% · ${fmtBytes(p.completed)} / ${fmtBytes(p.total)}` : '';
    $('#hf-install-model').textContent = p.local_name || '';
    $('#hf-install-cancel').hidden = !p.running;
    $('#hf-install-cancel').disabled = !p.cancellable;
    $('#hf-install-btn').disabled = !!p.running || !state.hfSelectedGroup;
  }

  async function startHFInstall() {
    const repo = state.hfRepo;
    const group = (state.hfGroups || []).find(g => g.id === state.hfSelectedGroup);
    if (!repo || !group || !group.complete) { setHFStatus('Choose a complete GGUF quant first.', 'error'); return; }
    const body = {
      repo_id: repo.repo_id,
      revision: repo.revision,
      group_id: group.id,
      local_name: String($('#hf-local-name')?.value || '').trim(),
      select_after: $('#hf-select-after')?.checked !== false,
    };
    $('#hf-install-btn').disabled = true;
    try {
      const p = await api('/api/hf/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      renderHFInstallState(p); setHFStatus(`Installing ${p.local_name || repo.repo_id}…`, 'ok');
      pollHFInstall();
    } catch (e) {
      $('#hf-install-btn').disabled = false; setHFStatus(e.message, 'error');
    }
  }

  async function pollHFInstall() {
    clearTimeout(state.hfPollTimer);
    try {
      const p = await api('/api/hf/install/status');
      renderHFInstallState(p);
      if (p.running) {
        state.hfPollTimer = setTimeout(pollHFInstall, 700);
        return;
      }
      if (p.phase === 'ready' && p.local_name) {
        await refreshRuntime({silent:true});
        setHFStatus(`Ready · ${p.local_name}`, 'ok');
        setComposeStatus(`Model ready · ${p.local_name}`);
        showToast(p.local_name, {title:'Hugging Face model ready', tone:'success', duration:2600});
      } else if (p.phase === 'failed') {
        setHFStatus(p.error || 'Hugging Face install failed.', 'error');
      } else if (p.phase === 'cancelled') {
        setHFStatus('Hugging Face install cancelled.');
      }
      $('#hf-install-btn').disabled = !state.hfSelectedGroup;
    } catch (e) {
      setHFStatus(e.message, 'error'); $('#hf-install-btn').disabled = !state.hfSelectedGroup;
    }
  }

  async function cancelHFInstall() {
    try {
      const p = await api('/api/hf/install/cancel',{method:'POST'});
      renderHFInstallState(p); setHFStatus('Cancelling Hugging Face install…'); pollHFInstall();
    } catch (e) { setHFStatus(e.message, 'error'); }
  }

  async function exportSessionById(id) {
    if (!id) return;
    try {
      const r = await fetch(`/api/sessions/${encodeURIComponent(id)}/export`); if (!r.ok) throw new Error('Export failed');
      const blob = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `matrixstudio2-${id.slice(0,12)}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
      showToast('Chat exported', {tone:'success', duration:2000});
    } catch (e) { setComposeStatus(e.message); }
  }

  async function exportChat() {
    return exportSessionById(state.session?.id);
  }

  async function uploadBackground(file) {
    if (!file) return;
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { $('#background-status').textContent = 'Use PNG, JPEG, or WebP'; return; }
    if (file.size > 12 * 1024 * 1024) { $('#background-status').textContent = 'Image exceeds 12 MB'; return; }
    $('#background-status').textContent = `Loading ${file.name}…`;
    const pending = collectSettings();
    try {
      const r = await fetch('/api/appearance/background', {method:'POST', headers:{'Content-Type':file.type}, body:file});
      if (!r.ok) { let d='Background upload failed'; try { d=(await r.json()).detail||d; } catch {} throw new Error(d); }
      const data = await r.json(); state.settings = {...(data.settings || state.settings), ...pending, background_image_enabled:true, background_image_version:data.settings?.background_image_version || Date.now()}; applyAppearance(); fillSettingsForm(); markDirty();
      $('#settings-status').textContent = 'Background installed · save visual settings when finished';
    } catch (e) { $('#background-status').textContent = e.message; }
  }

  async function removeBackground() {
    const pending = collectSettings();
    try {
      const data = await api('/api/appearance/background', {method:'DELETE'}); state.settings = {...(data.settings || state.settings), ...pending, background_image_enabled:false, background_image_version:data.settings?.background_image_version || Date.now()}; applyAppearance(); fillSettingsForm();
      $('#settings-status').textContent = 'Background removed';
    } catch (e) { $('#background-status').textContent = e.message; }
  }

  async function exportWorkspace() {
    try {
      const r = await fetch('/api/workspace/export'); if (!r.ok) throw new Error('Workspace export failed');
      const blob = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'MatrixStudio2.0-workspace.json'; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1200); $('#import-status').textContent = 'Workspace exported.';
    } catch (e) { $('#import-status').textContent = e.message; }
  }

  async function importWorkspace(file) {
    if (!file) return;
    $('#import-status').textContent = `Reading ${file.name}…`;
    try {
      const text = await file.text(); const payload = JSON.parse(text);
      const data = await api('/api/workspace/import', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      const fresh = await api('/api/state'); state.settings = fresh.settings || {}; state.runtime = fresh.runtime || {}; state.sessions = fresh.sessions || [];
      applyAppearance(); renderRuntime(); fillSettingsForm(); renderSessions(); $('#quick-think').value = state.settings.think_mode || 'auto';
      if (state.sessions[0]) await loadSession(state.sessions[0].id); else await createSession();
      $('#import-status').textContent = `Imported ${data.imported_sessions || 0} chat(s)${data.background_warning ? ' · '+data.background_warning : ''}.`;
    } catch (e) { $('#import-status').textContent = `Import failed · ${e.message}`; }
  }


  const THEME_KEYS = [
    'ui_mode','theme_preset','ui_density','ui_font_scale','chat_font_scale','reduce_motion','custom_colors_enabled',
    'accent_color','accent_secondary','background_color','panel_color','user_bubble_color','assistant_bubble_color','muted_text_color',
    'background_image_opacity','background_blur','background_dim','gradients_enabled','gradient_strength','panel_opacity','panel_blur','glow_strength'
  ];

  function exportTheme() {
    const source = $('#settings-dialog').open ? {...state.settings, ...collectSettings()} : state.settings;
    const appearance = {}; for (const key of THEME_KEYS) if (key in source) appearance[key] = source[key];
    const payload = {format:'matrixstudio2.theme', version:1, exported_at:new Date().toISOString(), appearance};
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'MatrixStudio2.0-theme.json'; a.click();
    setTimeout(()=>URL.revokeObjectURL(a.href), 1000); $('#import-status').textContent = 'Theme profile exported.';
  }

  async function importTheme(file) {
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      if (payload?.format !== 'matrixstudio2.theme' || !payload.appearance || typeof payload.appearance !== 'object') throw new Error('Not a MatrixStudio2.0 theme profile');
      const patch = {}; for (const key of THEME_KEYS) if (key in payload.appearance) patch[key] = payload.appearance[key];
      const data = await api('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(patch)});
      state.settings = data.settings || {...state.settings, ...patch}; applyAppearance(); fillSettingsForm(true); renderChat('keep');
      $('#import-status').textContent = `Theme profile imported from ${file.name}.`;
    } catch (e) { $('#import-status').textContent = `Theme import failed · ${e.message}`; }
  }

  function renderSpecialistStatus() {
    const selected = state.selectedSpecialist;
    const top = $('#specialist-top-status');
    if (top) top.textContent = selected ? selected.name : 'BASE';
    const name = $('#specialist-selected-name');
    const detail = $('#specialist-selected-detail');
    if (name) name.textContent = selected ? selected.name : 'Base assistant';
    if (detail) detail.textContent = selected ? `${selected.group} · manual specialist` : 'Be accurate, practical, concise, and complete.';
    const clear = $('#clear-specialist'); if (clear) clear.disabled = !selected;
  }

  async function loadSpecialistGroups({quiet=false} = {}) {
    try {
      const data = await api('/api/specialists/groups');
      state.specialistGroups = data.groups || [];
      state.selectedSpecialist = data.selected || null;
      if (!state.specialistGroup || !state.specialistGroups.some(g => g.id === state.specialistGroup)) state.specialistGroup = state.specialistGroups[0]?.id || '';
      const count = $('#specialist-count'); if (count) count.textContent = `${data.count || 0} local specialists`;
      renderSpecialistStatus();
      renderSpecialistGroups();
      if ($('#specialist-dialog')?.open) await loadSpecialistAgents();
      return data;
    } catch (e) {
      if (!quiet) setComposeStatus(`Specialists unavailable · ${e.message}`);
      return null;
    }
  }

  function renderSpecialistGroups() {
    const host = $('#specialist-groups'); if (!host) return;
    host.replaceChildren();
    state.specialistGroups.forEach(group => {
      const button = document.createElement('button'); button.type='button'; button.className=`specialist-group${group.id===state.specialistGroup?' active':''}`;
      const name=document.createElement('strong'); name.textContent=group.name;
      const count=document.createElement('span'); count.textContent=String(group.count ?? 0);
      button.append(name,count);
      button.addEventListener('click', async () => { state.specialistGroup=group.id; renderSpecialistGroups(); await loadSpecialistAgents(); });
      host.append(button);
    });
  }

  async function loadSpecialistAgents() {
    const host = $('#specialist-agents'); if (!host) return;
    host.innerHTML = '<div class="specialist-loading">Loading group…</div>';
    const q = ($('#specialist-search')?.value || '').trim();
    try {
      const params = new URLSearchParams(); if (state.specialistGroup) params.set('group',state.specialistGroup); if (q) params.set('q',q); params.set('limit','250');
      const data = await api(`/api/specialists?${params.toString()}`);
      state.specialistAgents = data.agents || [];
      host.replaceChildren();
      if (!state.specialistAgents.length) { const empty=document.createElement('div'); empty.className='specialist-empty'; empty.textContent='No specialists match this search.'; host.append(empty); return; }
      state.specialistAgents.forEach(agent => {
        const card=document.createElement('button'); card.type='button'; card.className=`specialist-agent${state.selectedSpecialist?.id===agent.id?' selected':''}`;
        const copy=document.createElement('div'); const title=document.createElement('strong'); title.textContent=agent.name; const desc=document.createElement('span'); desc.textContent=agent.description || agent.group; copy.append(title,desc);
        const action=document.createElement('em'); action.textContent=state.selectedSpecialist?.id===agent.id?'ACTIVE':'USE'; card.append(copy,action);
        card.addEventListener('click', async () => {
          await quickPatch({selected_specialist_id:agent.id});
          state.selectedSpecialist=agent; renderSpecialistStatus(); renderSpecialistGroups(); await loadSpecialistAgents();
          showToast(agent.name, {title:'Specialist', tone:'accent', duration:2400});
        });
        host.append(card);
      });
    } catch (e) { host.innerHTML=''; const err=document.createElement('div'); err.className='specialist-empty'; err.textContent=e.message; host.append(err); }
  }

  async function clearSpecialist() {
    await quickPatch({selected_specialist_id:''});
    state.selectedSpecialist=null; renderSpecialistStatus(); await loadSpecialistAgents(); showToast('Base assistant', {tone:'success', duration:2200});
  }

  async function openSpecialists() {
    const dialog=$('#specialist-dialog'); if (!dialog) return;
    if (!state.specialistGroups.length) await loadSpecialistGroups();
    renderSpecialistStatus(); renderSpecialistGroups(); await loadSpecialistAgents();
    if (!dialog.open) dialog.showModal();
    setTimeout(()=>$('#specialist-search')?.focus(),40);
  }

  async function refreshRetrievalStatus() {
    const target = $('#retrieval-status'); if (!target) return;
    try {
      const r = await api('/api/retrieval/status');
      const chunks = Number(r.knowledge_chunks || 0);
      const chats = Number(r.conversation_chunks || 0);
      const parts = [];
      parts.push(chunks ? `${chunks} knowledge chunk${chunks===1?'':'s'}` : 'Knowledge ready');
      parts.push(chats ? `${chats} cross-chat chunk${chats===1?'':'s'}` : 'Cross-chat index ready');
      target.textContent = parts.join(' · ');
    } catch {
      target.textContent = 'Quiet retrieval available';
    }
  }

  function activateSettingsTab(tab) {
    $$('.settings-tab').forEach(x => x.classList.toggle('active', x.dataset.tab === tab));
    $$('.settings-page').forEach(p => p.classList.toggle('active', p.dataset.page === tab));
    if (tab === 'chat') refreshRetrievalStatus();
    if (tab === 'voice') { refreshTTSStatus(); refreshSTTStatus(); }
  }

  function filterSettings(query='') {
    const q=String(query||'').trim().toLowerCase();
    const tabs=$$('.settings-tab');
    const matches=[];
    tabs.forEach(tab => {
      const page=$(`.settings-page[data-page="${tab.dataset.tab}"]`);
      const hit=!q || `${tab.textContent} ${page?.textContent||''}`.toLowerCase().includes(q);
      tab.hidden=!hit; if(hit) matches.push(tab.dataset.tab);
    });
    if (q && matches.length) {
      const active=$('.settings-tab.active');
      if (!active || active.hidden) activateSettingsTab(matches[0]);
    } else if (!matches.length && q) {
      $$('.settings-page').forEach(p=>p.classList.remove('active'));
    } else if (!q && !$('.settings-tab.active')) {
      activateSettingsTab('runtime');
    }
    $('#settings-dialog')?.classList.toggle('settings-search-empty', !!q && !matches.length);
  }

  function retryLastResponse() {
    const msgs = state.session?.messages || [];
    const idx = previousUserIndex(msgs, msgs.length - 1);
    if (idx >= 0) retryUserMessage(idx); else setComposeStatus('Nothing to retry yet');
  }

  function commandCatalog() {
    return [
      {label:'New chat', hint:'Ctrl N', run:createSession},
      {label:'Focus message box', hint:'Esc to close panels', run:()=>$('#chat-input').focus()},
      {label:'Search conversations', hint:'/', run:()=>{ revealSidebar(); $('#session-search').focus(); }},
      {label:'Runtime settings', hint:'Settings', run:()=>openSettings('runtime')},
      {label:'Chat settings', hint:'Settings', run:()=>openSettings('chat')},
      {label:'Reasoning settings', hint:'Settings', run:()=>openSettings('reasoning')},
      {label:'Manual specialists', hint:'700 local roles', run:openSpecialists},
      {label:'Appearance settings', hint:'Settings', run:()=>openSettings('appearance')},
      {label:'Import / Export', hint:'Settings', run:()=>openSettings('data')},
      {label:'Reconnect local runtime', hint:'No restart', run:()=>reconnectRuntime()},
      {label:'Retry last response', hint:'Regenerate', run:retryLastResponse},
      {label:'Export current chat', hint:'JSON', run:exportChat},
      {label:'Toggle sidebar', hint:'Layout', run:()=>$('#sidebar-toggle').click()},
    ];
  }

  function renderCommandPalette() {
    const q = ($('#command-input').value || '').trim().toLowerCase();
    const all = commandCatalog();
    const filtered = all.filter(c => !q || `${c.label} ${c.hint || ''}`.toLowerCase().includes(q));
    state.commandItems = filtered; state.commandIndex = clamp(state.commandIndex, 0, Math.max(0, filtered.length - 1));
    const list = $('#command-list'); list.replaceChildren();
    filtered.forEach((cmd, i) => {
      const b = document.createElement('button'); b.type='button'; b.className=`command-item${i===state.commandIndex?' active':''}`;
      const label=document.createElement('strong'); label.textContent=cmd.label; const hint=document.createElement('span'); hint.textContent=cmd.hint||'';
      b.append(label,hint); b.addEventListener('click',()=>runCommand(i)); list.append(b);
    });
    if (!filtered.length) { const empty=document.createElement('div'); empty.className='command-empty'; empty.textContent='No matching command'; list.append(empty); }
  }

  function openCommandPalette() {
    const dialog = $('#command-dialog'); state.commandIndex=0; $('#command-input').value=''; renderCommandPalette();
    if (!dialog.open) dialog.showModal(); setTimeout(()=>$('#command-input').focus(),20);
  }

  function runCommand(index = state.commandIndex) {
    const cmd = state.commandItems?.[index]; if (!cmd) return;
    $('#command-dialog').close(); try { Promise.resolve(cmd.run()).catch(e=>setComposeStatus(e.message)); } catch(e) { setComposeStatus(e.message); }
  }

  function openSettings(tab = 'runtime') {
    fillSettingsForm();
    const search=$('#settings-search'); if (search) search.value='';
    $$('.settings-tab').forEach(x=>x.hidden=false); $('#settings-dialog')?.classList.remove('settings-search-empty');
    activateSettingsTab(tab);
    $('#settings-dialog').showModal();
  }

  async function shutdownStudio(source = 'settings') {
    if (state.shutdownActive) return;

    state.shutdownActive = true;
    clearTimeout(state.settingsSaveTimer); state.settingsSaveTimer = null;
    const settingsDialog = $('#settings-dialog');
    const settingsWasOpen = !!settingsDialog?.open;
    if (settingsWasOpen) settingsDialog.close();
    const buttons = [$('#kill-localhost'), $('#kill-host-exit')].filter(Boolean);
    buttons.forEach(button => { button.disabled = true; });
    const overlay = $('#shutdown-overlay');
    const status = $('#shutdown-status');
    if (status) status.textContent = 'Saving workspace state…';
    if (overlay) { overlay.hidden = false; overlay.setAttribute('aria-hidden', 'false'); }
    document.body.classList.add('shutdown-in-progress');

    const shutdownSettings = collectSettings();
    const shutdownUi = {...sessionViewSnapshot(), sidebar_collapsed:sidebarCollapsedSnapshot()};
    try {
      const request = api('/api/runtime/kill', {
        method:'POST',
        headers:{'X-Matrix-Action':'shutdown','Content-Type':'application/json'},
        body:JSON.stringify({settings:shutdownSettings,ui_state:shutdownUi})
      });
      await Promise.all([request, new Promise(resolve => setTimeout(resolve, 420))]);
      if (status) status.textContent = 'Host offline · closing MatrixStudio2.0…';
      stopChat();
      setComposeStatus('Host stopped. Settings saved.');
      $('#chat-input').disabled = true; $('#send-chat').disabled = true;
    } catch (e) {
      state.shutdownActive = false;
      document.body.classList.remove('shutdown-in-progress');
      if (overlay) { overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true'); }
      buttons.forEach(button => { button.disabled = false; });
      if (settingsWasOpen && settingsDialog && !settingsDialog.open) settingsDialog.showModal();
      if ($('#settings-status')) $('#settings-status').textContent = e.message;
      setComposeStatus(`Shutdown cancelled · ${e.message}`);
    }
  }

  function bind() {
    document.querySelectorAll('.color-field input').forEach(input=>input.addEventListener('input',()=>{ $('#set-custom-colors').checked=true; }));
    $('#kill-localhost')?.addEventListener('click', () => shutdownStudio('settings'));
    $('#kill-host-exit')?.addEventListener('click', () => shutdownStudio('quick'));
    $('#new-chat').addEventListener('click', createSession); $('#send-chat').addEventListener('click', sendChat); $('#stop-chat').addEventListener('click', () => stopChat(true)); $('#export-chat').addEventListener('click', exportChat);
    $('#live-call')?.addEventListener('click', () => { void startLiveCall(); });
    $('#live-call-mute')?.addEventListener('click', toggleLiveMute);
    $('#stop-voice-main')?.addEventListener('click', () => { stopSpeech({notifyBackend:true, release:false}); if (state.liveCall.active && state.liveCall.state === 'SPEAKING') { state.liveCall.processing = false; setTimeout(resumeLiveListening, 40); } });
    $('#chat-input').addEventListener('input', () => {
      autoSizeInput();
      const sid = state.session?.id || '';
      const drafts = {...(state.uiState?.session_drafts || {})}; if (sid) drafts[sid] = $('#chat-input').value;
      state.uiState = {...state.uiState, draft:$('#chat-input').value, session_drafts:drafts}; persistUiState({draft:$('#chat-input').value, session_drafts:drafts});
      if (!(state.session?.messages || []).length) renderSessions();
    });
    $('#chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } else if (e.key === 'Escape' && state.abort) stopChat(true); });
    $('#messages').addEventListener('scroll', () => { clearTimeout(state.sessionViewTimer); state.sessionViewTimer=setTimeout(()=>persistCurrentSessionView(0),120); }, {passive:true});
    $('#quick-model-trigger').addEventListener('click', () => openControlMenu('model', $('#quick-model-trigger')));
    $('#quick-think-trigger').addEventListener('click', () => openControlMenu('think', $('#quick-think-trigger')));
    $('#quick-model').addEventListener('change', async (e) => { await patchSessionGeneration({model:e.target.value}); }); $('#quick-think').addEventListener('change', async (e) => { await patchSessionGeneration({think_mode:e.target.value}); });
    $('#control-menu-close').addEventListener('click', () => closeControlMenu({focus:true}));
    $('#control-menu-search').addEventListener('input', e => { if (!state.controlMenu) return; state.controlMenu.filter = e.target.value || ''; renderControlMenuList(); positionControlMenu(); });
    $('#open-settings').addEventListener('click', () => openSettings('runtime')); $('#open-settings-side').addEventListener('click', () => openSettings('appearance')); $('#model-alert-settings').addEventListener('click', () => openSettings('runtime')); $('#model-alert-reconnect').addEventListener('click', () => reconnectRuntime());
    $('#open-specialists').addEventListener('click', openSpecialists); $('#close-specialists').addEventListener('click',()=>$('#specialist-dialog').close()); $('#specialist-done').addEventListener('click',()=>$('#specialist-dialog').close()); $('#clear-specialist').addEventListener('click', clearSpecialist);
    let specialistSearchTimer=0; $('#specialist-search').addEventListener('input',()=>{clearTimeout(specialistSearchTimer);specialistSearchTimer=setTimeout(loadSpecialistAgents,120);}); $('#specialist-dialog').addEventListener('click',e=>{if(e.target===$('#specialist-dialog'))$('#specialist-dialog').close();});
    $('#install-starter').addEventListener('click', () => { openSettings('runtime'); setTimeout(() => startPull(state.runtime.starter_model || 'llama3.2:3b'), 50); }); $('#starter-chip').addEventListener('click', () => { $('#pull-model').value = state.runtime.starter_model || 'llama3.2:3b'; });
    $('#close-settings').addEventListener('click', async () => { if (state.dirty && !(await saveSettings())) return; $('#settings-dialog').close(); }); $('#settings-form').addEventListener('submit', e => e.preventDefault());
    $$('.settings-tab').forEach(btn => btn.addEventListener('click', () => activateSettingsTab(btn.dataset.tab)));
    $('#settings-search').addEventListener('input',e=>filterSettings(e.target.value));
    $('#save-settings').addEventListener('click', saveSettings); $('#reset-all').addEventListener('click', () => openSettings('advanced')); $('#reset-program-state').addEventListener('click', () => resetSection('all')); $$('.reset-section').forEach(b => b.addEventListener('click', () => resetSection(b.dataset.section)));
    $('#launch-cleaner')?.addEventListener('click', async () => { const button=$('#launch-cleaner'); button.disabled=true; try { const r=await api('/api/maintenance/cleaner',{method:'POST',headers:{'X-Matrix-Action':'maintenance'}}); showToast(r.tool || 'CYPRA CLEAN', {title:'System maintenance', tone:'success', duration:2600}); if ($('#settings-status')) $('#settings-status').textContent='CYPRA CLEAN launched · approve the Windows UAC prompt.'; } catch(e) { showToast(e.message, {title:'Cleaner launch failed', tone:'danger', duration:3800}); if ($('#settings-status')) $('#settings-status').textContent=e.message; } finally { button.disabled=false; } });
    $('#open-knowledge-folder')?.addEventListener('click', async () => { const button=$('#open-knowledge-folder'); button.disabled=true; try { const r=await api('/api/retrieval/open-folder',{method:'POST',headers:{'X-Matrix-Action':'retrieval'}}); $('#retrieval-status').textContent = r.opened === false ? r.path : 'Knowledge folder opened'; } catch(e) { $('#retrieval-status').textContent=e.message; } finally { button.disabled=false; } });
    $('#reindex-knowledge')?.addEventListener('click', async () => { const button=$('#reindex-knowledge'); button.disabled=true; $('#retrieval-status').textContent='Reindexing…'; try { const r=await api('/api/retrieval/reindex',{method:'POST',headers:{'X-Matrix-Action':'retrieval'}}); $('#retrieval-status').textContent=`${r.knowledge_chunks||0} knowledge · ${r.conversation_chunks||0} cross-chat chunks indexed`; } catch(e) { $('#retrieval-status').textContent=e.message; } finally { button.disabled=false; } });
    $('#refresh-runtime').addEventListener('click', refreshRuntime); $('#reconnect-runtime').addEventListener('click', () => reconnectRuntime());
    $('#warm-model').addEventListener('click', async () => { setComposeStatus('Warming model…'); try { const r=await api('/api/llm/warm',{method:'POST'}); setComposeStatus(`Warm · ${r.model}`); await refreshRuntime(); } catch(e) { setComposeStatus(e.message); } });
    $('#unload-model').addEventListener('click', async () => { try { const r=await api('/api/llm/unload',{method:'POST'}); setComposeStatus(`Unloaded ${r.unloaded?.length||0} model(s)`); await refreshRuntime(); } catch(e) { setComposeStatus(e.message); } });
    $('#pull-model-btn').addEventListener('click', () => startPull());
    $('#hf-search-btn').addEventListener('click', searchHF);
    $('#hf-search').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); searchHF(); } });
    $('#hf-sort').addEventListener('change', renderHFGroups);
    $('#hf-install-btn').addEventListener('click', startHFInstall);
    $('#hf-install-cancel').addEventListener('click', cancelHFInstall);
    $('#choose-background').addEventListener('click', () => $('#background-file').click()); $('#background-file').addEventListener('change', e => { const file=e.target.files?.[0]; if (file) uploadBackground(file); e.target.value=''; }); $('#remove-background').addEventListener('click', removeBackground);
    $('#export-workspace').addEventListener('click', exportWorkspace); $('#import-workspace').addEventListener('click', () => $('#import-workspace-file').click()); $('#import-workspace-file').addEventListener('change', e => { const file=e.target.files?.[0]; if (file) importWorkspace(file); e.target.value=''; });
    $('#export-theme').addEventListener('click', exportTheme); $('#import-theme').addEventListener('click', () => $('#import-theme-file').click()); $('#import-theme-file').addEventListener('change', e => { const file=e.target.files?.[0]; if (file) importTheme(file); e.target.value=''; });
    $('#set-temperature').addEventListener('input', e => $('#temp-output').value=Number(e.target.value).toFixed(2)); $('#set-ui-scale').addEventListener('input',e=>$('#ui-scale-output').value=Number(e.target.value).toFixed(2)); $('#set-chat-scale').addEventListener('input',e=>$('#chat-scale-output').value=Number(e.target.value).toFixed(2));
    $('#set-tts-rate').addEventListener('input', e => $('#tts-rate-output').value=Number(e.target.value).toFixed(2)); $('#set-tts-pitch').addEventListener('input', e => $('#tts-pitch-output').value=Number(e.target.value).toFixed(2)); $('#set-tts-volume').addEventListener('input', e => $('#tts-volume-output').value=Number(e.target.value).toFixed(2)); $('#set-tts-intensity').addEventListener('input', e => $('#tts-intensity-output').value=`${Math.round(Number(e.target.value)*100)}%`);
    $('#voice-preview').addEventListener('click', () => speakText('Matrix Studio voice systems online.', {preview:true, provider:$('#set-tts-provider').value, button:$('#voice-preview')}).catch(e => showToast(e.message || 'Voice preview failed', {title:'Voice', tone:'danger', duration:3200})));
    $('#voice-stop').addEventListener('click', () => stopSpeech({notifyBackend:true, release:false}));
    $('#set-voice-output').addEventListener('change', e => { state.settings.voice_output_enabled = !!e.target.checked; if (!e.target.checked) { stopSpeech({notifyBackend:true, release:true}); if (state.liveCall.active) void endLiveCall(); } renderChat('keep'); setTimeout(refreshTTSStatus, 180); });
    $('#set-tts-provider').addEventListener('change', () => { void handleTTSProviderChange(); });
    $('#set-tts-allow-online').addEventListener('change', () => { void handleTTSOnlineChange(); });
    $('#set-tts-edge-voice').addEventListener('change', () => { state.settings.tts_edge_voice = $('#set-tts-edge-voice').value; void persistSettingsSnapshot(collectSettings()).catch(e => { if ($('#tts-status')) $('#tts-status').textContent = e.message; }); });
    $('#refresh-edge-voices').addEventListener('click', () => { void loadEdgeVoices({force:true}).catch(e => showToast(e.message || 'Edge voice discovery failed', {title:'Voice', tone:'danger', duration:3200})); });
    $('#prepare-local-stt')?.addEventListener('click', () => { void prepareLocalSTTFromSettings(); });
    const outputBindings = [
      ['set-background-opacity','background-opacity-output',v=>Number(v).toFixed(2)],
      ['set-background-blur','background-blur-output',v=>`${Number(v).toFixed(0)}px`],
      ['set-background-dim','background-dim-output',v=>Number(v).toFixed(2)], ['set-gradient-strength','gradient-strength-output',v=>Number(v).toFixed(2)],
      ['set-panel-opacity','panel-opacity-output',v=>Number(v).toFixed(2)], ['set-panel-blur','panel-blur-output',v=>`${Number(v).toFixed(0)}px`], ['set-glow-strength','glow-strength-output',v=>Number(v).toFixed(2)]
    ];
    outputBindings.forEach(([id,out,fmt]) => $('#'+id).addEventListener('input', e => $('#'+out).value=fmt(e.target.value)));
    const colorBindings = [['set-accent-color','accent-color-value'],['set-accent-secondary','accent-secondary-value'],['set-background-color','background-color-value'],['set-panel-color','panel-color-value'],['set-user-bubble-color','user-bubble-color-value'],['set-assistant-bubble-color','assistant-bubble-color-value'],['set-muted-text-color','muted-text-color-value']];
    colorBindings.forEach(([id,out]) => $('#'+id).addEventListener('input', e => $('#'+out).textContent=e.target.value));
    $$('#settings-dialog input,#settings-dialog select,#settings-dialog textarea').forEach(el => {
      if (['set-tts-provider','set-tts-allow-online','set-tts-edge-voice'].includes(el.id)) return;
      el.addEventListener('input', markDirty); el.addEventListener('change', flushSettingsAutosave);
    });
    ['set-gradients','set-gradient-strength','set-ui-mode','set-theme','set-density','set-ui-scale','set-chat-scale','set-reduce-motion','set-custom-colors','set-accent-color','set-accent-secondary','set-background-color','set-panel-color','set-user-bubble-color','set-assistant-bubble-color','set-muted-text-color','set-background-opacity','set-background-blur','set-background-dim','set-panel-opacity','set-panel-blur','set-glow-strength'].forEach(id => $('#'+id).addEventListener('input', () => { const preview={...state.settings,...collectSettings()}; applyAppearance(preview); }));
    $('#session-search').addEventListener('input', e => { state.search = e.target.value; renderSessions(); });
    $('#session-list').addEventListener('scroll', () => closeSessionMenus(), {passive:true});
    $('#sidebar-toggle').addEventListener('click', () => {
      document.body.classList.toggle('sidebar-collapsed');
      persistUiState({sidebar_collapsed:document.body.classList.contains('sidebar-collapsed')});
    });
    $('#command-input').addEventListener('input', () => { state.commandIndex=0; renderCommandPalette(); });
    $('#command-input').addEventListener('keydown', e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); state.commandIndex=clamp(state.commandIndex+1,0,Math.max(0,(state.commandItems?.length||1)-1)); renderCommandPalette(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); state.commandIndex=clamp(state.commandIndex-1,0,Math.max(0,(state.commandItems?.length||1)-1)); renderCommandPalette(); }
      else if (e.key === 'Enter') { e.preventDefault(); runCommand(); }
      else if (e.key === 'Escape') { e.preventDefault(); $('#command-dialog').close(); }
    });
    $('#command-dialog').addEventListener('click', e => { if (e.target === $('#command-dialog')) $('#command-dialog').close(); });
    document.addEventListener('click', e => {
      if (!e.target.closest('.session-more') && !e.target.closest('.session-menu')) closeSessionMenus();
      if (!e.target.closest('#control-menu-panel') && !e.target.closest('.quick-menu-trigger')) closeControlMenu();
    });
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase()==='k') { e.preventDefault(); openCommandPalette(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase()==='n') { e.preventDefault(); createSession(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key===',') { e.preventDefault(); openSettings('runtime'); return; }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase()==='r') { e.preventDefault(); retryLastResponse(); return; }
      if (e.key==='/' && !e.ctrlKey && !e.metaKey && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'INPUT') { e.preventDefault(); revealSidebar(); $('#session-search').focus(); return; }
      if (e.key==='Escape') {
        if (state.controlMenu) { e.preventDefault(); closeControlMenu({focus:true}); return; }
        if (state.sessionMenu) { e.preventDefault(); closeSessionMenus(); return; }
        if ($('#command-dialog').open) { e.preventDefault(); $('#command-dialog').close(); return; }
        if ($('#specialist-dialog').open) { e.preventDefault(); $('#specialist-dialog').close(); return; }
        if ($('#settings-dialog').open) { e.preventDefault(); if (state.dirty) scheduleSettingsAutosave(0); $('#settings-dialog').close(); return; }
        if (state.abort) { e.preventDefault(); stopChat(true); }
      }
    });
  }

  async function init() {
    bind(); autoSizeInput(); buildAmbientParticles(); syncGenerationState();
    try {
      const data = await api('/api/state'); state.settings = data.settings || {}; state.runtime = data.runtime || {}; state.sessions = data.sessions || []; state.uiState = data.ui_state || {};
      $('#build-id').textContent = data.build_id || '—'; applyAppearance(); renderRuntime(); $('#quick-think').value = state.settings.think_mode || 'auto'; syncQuickControlLabels(); fillSettingsForm(); renderSessions();
      await refreshTTSStatus();
      await refreshSTTStatus();
      await loadSpecialistGroups({quiet:true});
      syncResponsiveShell();
      const remembered = state.sessions.find(s => s.id === state.uiState.active_session_id);
      if (remembered) await loadSession(remembered.id); else if (state.sessions[0]) await loadSession(state.sessions[0].id); else await createSession();
      armMotion(); startRuntimeWatch();
      const pull = await api('/api/llm/pull/status').catch(()=>null); if (pull?.running) pollPull();
      const hfInstall = await api('/api/hf/install/status').catch(()=>null); if (hfInstall) { renderHFInstallState(hfInstall); if (hfInstall.running) pollHFInstall(); }
      $('#chat-input').focus();
    } catch (e) { setComposeStatus(`Startup error · ${e.message}`); }
  }

  init();
})();
