/* Звук: синтезируется на лету через WebAudio — внешних файлов нет. */
(function (global) {
  "use strict";

  let ctx = null;
  let enabled = true;

  try {
    enabled = localStorage.getItem("pref_sound") !== "off";
  } catch (e) { /* приватный режим */ }

  function ensure() {
    if (!ctx) {
      const Ctx = global.AudioContext || global.webkitAudioContext;
      if (!Ctx) return null;
      ctx = new Ctx();
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  function noiseBuffer(duration) {
    const count = Math.floor(ctx.sampleRate * duration);
    const buffer = ctx.createBuffer(1, count, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < count; i++) {
      data[i] = (Math.random() * 2 - 1) * (1 - i / count);
    }
    return buffer;
  }

  function burst(duration, freq, gainValue, type) {
    const audio = ensure();
    if (!audio) return;
    const source = audio.createBufferSource();
    source.buffer = noiseBuffer(duration);
    const filter = audio.createBiquadFilter();
    filter.type = type || "bandpass";
    filter.frequency.value = freq;
    filter.Q.value = 0.8;
    const gain = audio.createGain();
    gain.gain.value = gainValue;
    source.connect(filter).connect(gain).connect(audio.destination);
    source.start();
  }

  function tone(freq, start, duration, gainValue, type) {
    const audio = ensure();
    if (!audio) return;
    const osc = audio.createOscillator();
    osc.type = type || "sine";
    osc.frequency.value = freq;
    const gain = audio.createGain();
    const t0 = audio.currentTime + start;
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(gainValue, t0 + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
    osc.connect(gain).connect(audio.destination);
    osc.start(t0);
    osc.stop(t0 + duration + 0.05);
  }

  const SOUNDS = {
    deal() { burst(0.07, 2600, 0.16); },
    play() { burst(0.045, 3400, 0.2); },
    trick() { tone(660, 0, 0.1, 0.06, "sine"); tone(880, 0.07, 0.13, 0.05, "sine"); },
    bid() { tone(520, 0, 0.08, 0.05, "triangle"); tone(700, 0.06, 0.1, 0.04, "triangle"); },
    win() { [523, 659, 784, 1046].forEach((f, i) => tone(f, i * 0.11, 0.3, 0.07, "triangle")); },
    lose() { [392, 330, 262].forEach((f, i) => tone(f, i * 0.12, 0.32, 0.06, "sine")); },
    error() { tone(180, 0, 0.16, 0.07, "sawtooth"); }
  };

  global.Sound = {
    play(name) {
      if (!enabled) return;
      try {
        const fn = SOUNDS[name];
        if (fn) fn();
      } catch (e) { /* звук не критичен */ }
    },
    get enabled() { return enabled; },
    setEnabled(value) {
      enabled = !!value;
      try { localStorage.setItem("pref_sound", enabled ? "on" : "off"); } catch (e) { /* игнор */ }
      if (enabled) this.play("bid");
    },
    toggle() { this.setEnabled(!enabled); return enabled; }
  };
})(window);
