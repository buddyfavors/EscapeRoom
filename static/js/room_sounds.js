/**
 * Escape room sound cues, synthesized via Web Audio (no sound files; works offline on the Pi).
 * Browsers require a user gesture before audio — resume() is wired to the first tap / key press.
 */
(function (global) {
  let ctx = null;
  let master = null;
  let noiseBuf = null;

  function getCtx() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = 0.8;
      master.connect(ctx.destination);
    }
    return ctx;
  }

  function resume() {
    const c = getCtx();
    if (c && c.state === "suspended") {
      c.resume().catch(function () {});
    }
  }

  function noise() {
    const c = getCtx();
    if (!noiseBuf) {
      noiseBuf = c.createBuffer(1, c.sampleRate, c.sampleRate);
      const data = noiseBuf.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    }
    const src = c.createBufferSource();
    src.buffer = noiseBuf;
    src.loop = true;
    return src;
  }

  function envGain(t0, peak, attack, hold, release) {
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(peak, t0 + attack);
    g.gain.setValueAtTime(peak, t0 + attack + hold);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + attack + hold + release);
    return g;
  }

  function staticBurst(t0, duration, volume, freq) {
    const src = noise();
    const bp = ctx.createBiquadFilter();
    bp.type = "bandpass";
    bp.frequency.value = freq || 2400;
    bp.Q.value = 0.7;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t0);
    // Choppy on/off gating reads as a dying signal rather than plain hiss.
    const steps = Math.max(3, Math.round(duration / 0.03));
    for (let i = 0; i < steps; i++) {
      const t = t0 + (i * duration) / steps;
      g.gain.setValueAtTime(Math.random() < 0.7 ? volume * (0.4 + Math.random() * 0.6) : 0.0001, t);
    }
    g.gain.setValueAtTime(0.0001, t0 + duration);
    src.connect(bp);
    bp.connect(g);
    g.connect(master);
    src.start(t0);
    src.stop(t0 + duration + 0.05);
  }

  function osc(type, freq, t0, duration, volume, endFreq) {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(freq, t0);
    if (endFreq) o.frequency.exponentialRampToValueAtTime(endFreq, t0 + duration);
    const g = envGain(t0, volume, 0.005, Math.max(0, duration - 0.06), 0.05);
    o.connect(g);
    g.connect(master);
    o.start(t0);
    o.stop(t0 + duration + 0.1);
    return o;
  }

  function play(fn) {
    const c = getCtx();
    if (!c) return;
    resume();
    fn(c.currentTime + 0.02);
  }

  global.RoomSounds = {
    resume,

    /** Broken clue: static crackle + stuttering descending blips. */
    glitch() {
      play(function (t0) {
        staticBurst(t0, 0.4, 0.22, 1800);
        for (let i = 0; i < 4; i++) {
          const f = 900 - i * 170 + Math.random() * 60;
          osc("square", f, t0 + i * 0.07, 0.05, 0.06);
        }
        osc("sawtooth", 160, t0 + 0.3, 0.25, 0.08, 60);
      });
    },

    /** Minor rejection (spent / unknown tag). */
    buzz() {
      play(function (t0) {
        osc("square", 140, t0, 0.18, 0.07);
        staticBurst(t0, 0.12, 0.08, 3000);
      });
    },

    /** Working clue recovered: clean two-note data chirp. */
    chirp() {
      play(function (t0) {
        osc("sine", 880, t0, 0.07, 0.08);
        osc("sine", 1320, t0 + 0.08, 0.12, 0.08);
      });
    },

    /** Klaxon for punishments. */
    alarm(cycles) {
      play(function (t0) {
        const n = cycles || 3;
        for (let i = 0; i < n; i++) {
          const t = t0 + i * 0.8;
          const o = ctx.createOscillator();
          o.type = "sawtooth";
          o.frequency.setValueAtTime(420, t);
          o.frequency.linearRampToValueAtTime(680, t + 0.55);
          const lp = ctx.createBiquadFilter();
          lp.type = "lowpass";
          lp.frequency.value = 1600;
          const g = envGain(t, 0.12, 0.03, 0.5, 0.15);
          o.connect(lp);
          lp.connect(g);
          g.connect(master);
          o.start(t);
          o.stop(t + 0.75);
        }
      });
    },

    /** Low hum under the intro. */
    drone(seconds) {
      play(function (t0) {
        const dur = seconds || 8;
        const lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.value = 260;
        const g = envGain(t0, 0.16, 1.2, Math.max(0, dur - 2.4), 1.2);
        lp.connect(g);
        g.connect(master);
        [55, 55.6, 82.4].forEach(function (f) {
          const o = ctx.createOscillator();
          o.type = "sawtooth";
          o.frequency.value = f;
          o.connect(lp);
          o.start(t0);
          o.stop(t0 + dur + 0.1);
        });
        staticBurst(t0, 0.5, 0.15, 2600);
      });
    },

    /** One typewriter tick for the intro text. */
    typeTick() {
      play(function (t0) {
        const src = noise();
        const hp = ctx.createBiquadFilter();
        hp.type = "highpass";
        hp.frequency.value = 3500;
        const g = envGain(t0, 0.05, 0.001, 0.004, 0.02);
        src.connect(hp);
        hp.connect(g);
        g.connect(master);
        src.start(t0);
        src.stop(t0 + 0.04);
      });
    },

    /** Finale: restraints clank open, a rising sweep, then a held major chord with sparkles. */
    fanfare() {
      play(function (t0) {
        [0, 0.32].forEach(function (dt) {
          staticBurst(t0 + dt, 0.12, 0.25, 900);
          osc("square", 120, t0 + dt, 0.18, 0.12, 45);
        });
        osc("sawtooth", 110, t0 + 0.6, 1.0, 0.05, 880);
        [523, 659, 784, 1046, 1319].forEach(function (f, i) {
          osc("triangle", f, t0 + 1.4 + i * 0.11, 0.35, 0.08);
        });

        const tc = t0 + 2.0;
        const lp = ctx.createBiquadFilter();
        lp.type = "lowpass";
        lp.frequency.setValueAtTime(600, tc);
        lp.frequency.linearRampToValueAtTime(2400, tc + 1.2);
        const g = envGain(tc, 0.05, 0.4, 2.2, 1.6);
        lp.connect(g);
        g.connect(master);
        [261.6, 329.6, 392, 523.3].forEach(function (f) {
          [["sawtooth", 1.003], ["triangle", 2]].forEach(function (voice) {
            const o = ctx.createOscillator();
            o.type = voice[0];
            o.frequency.value = f * voice[1];
            o.connect(lp);
            o.start(tc);
            o.stop(tc + 4.4);
          });
        });
        for (let i = 0; i < 10; i++) {
          osc("sine", 1568 + Math.random() * 1600, tc + 0.3 + i * 0.22, 0.12, 0.03);
        }
      });
    },

    /** Power-down for a Gamemaster win. */
    powerDown() {
      play(function (t0) {
        osc("sawtooth", 440, t0, 2.2, 0.12, 30);
        osc("square", 220, t0, 2.0, 0.05, 20);
        staticBurst(t0 + 1.6, 0.8, 0.18, 1200);
      });
    },
  };

  function unlock() {
    resume();
    window.removeEventListener("pointerdown", unlock, true);
    window.removeEventListener("keydown", unlock, true);
  }
  window.addEventListener("pointerdown", unlock, true);
  window.addEventListener("keydown", unlock, true);
})(window);
