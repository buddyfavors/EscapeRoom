/**
 * Short synthesized cues via Web Audio (no sound files; works offline on the Pi).
 * Browsers require a user gesture before audio — call resume() from Start / first tap.
 */
(function (global) {
  let ctx = null;

  function getCtx() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
    }
    return ctx;
  }

  function resume() {
    const c = getCtx();
    if (c && c.state === "suspended") {
      c.resume().catch(function () {});
    }
  }

  function tone(freq, duration, volume, type, when) {
    const c = getCtx();
    if (!c) return;
    const t0 = when != null ? when : c.currentTime;
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = type || "sine";
    osc.frequency.setValueAtTime(freq, t0);
    const v = Math.min(0.25, Math.max(0.001, volume));
    g.gain.setValueAtTime(v, t0);
    g.gain.exponentialRampToValueAtTime(0.0008, t0 + Math.max(0.02, duration));
    osc.connect(g);
    g.connect(c.destination);
    osc.start(t0);
    osc.stop(t0 + duration + 0.02);
  }

  function sequence(steps) {
    const c = getCtx();
    if (!c) return;
    let t = c.currentTime + 0.01;
    for (let i = 0; i < steps.length; i++) {
      const s = steps[i];
      tone(s.f, s.d, s.v || 0.1, s.type || "sine", t);
      t += s.gap != null ? s.gap : s.d;
    }
  }

  global.MinigameSounds = {
    resume,

    reactionGo() {
      sequence([
        { f: 660, d: 0.06, v: 0.12, gap: 0.02 },
        { f: 990, d: 0.1, v: 0.14 },
      ]);
    },

    reactionHit() {
      sequence([
        { f: 523, d: 0.05, v: 0.1, gap: 0.02 },
        { f: 659, d: 0.05, v: 0.1, gap: 0.02 },
        { f: 784, d: 0.12, v: 0.12 },
      ]);
    },

    reactionMiss() {
      const c = getCtx();
      if (!c) return;
      const t0 = c.currentTime + 0.01;
      tone(180, 0.18, 0.14, "sawtooth", t0);
      tone(140, 0.22, 0.1, "square", t0 + 0.05);
    },

    reactionWin() {
      sequence([
        { f: 523, d: 0.08, v: 0.1, gap: 0.04 },
        { f: 659, d: 0.08, v: 0.1, gap: 0.04 },
        { f: 784, d: 0.08, v: 0.1, gap: 0.04 },
        { f: 1046, d: 0.2, v: 0.12 },
      ]);
    },

    reactionLose() {
      sequence([
        { f: 392, d: 0.12, v: 0.11, gap: 0.05 },
        { f: 330, d: 0.15, v: 0.11, gap: 0.05 },
        { f: 262, d: 0.25, v: 0.12 },
      ]);
    },

    whackRound() {
      tone(440, 0.06, 0.09, "triangle");
    },

    whackSafeTap() {
      tone(880, 0.04, 0.08, "sine");
    },

    whackTrap() {
      const c = getCtx();
      if (!c) return;
      const t0 = c.currentTime + 0.01;
      for (let i = 0; i < 6; i++) {
        tone(95 + i * 35, 0.05, 0.13 - i * 0.015, "sawtooth", t0 + i * 0.045);
      }
    },

    whackRoundClear() {
      sequence([
        { f: 587, d: 0.06, v: 0.09, gap: 0.03 },
        { f: 740, d: 0.08, v: 0.1, gap: 0.03 },
        { f: 988, d: 0.14, v: 0.11 },
      ]);
    },

    whackTimeout() {
      sequence([
        { f: 349, d: 0.1, v: 0.1, gap: 0.04 },
        { f: 294, d: 0.18, v: 0.1 },
      ]);
    },

    whackWin() {
      global.MinigameSounds.reactionWin();
    },

    whackLose() {
      global.MinigameSounds.reactionLose();
    },
  };
})(window);
