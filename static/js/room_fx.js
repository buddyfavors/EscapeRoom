/**
 * Play screen visuals: screen glitch, red alarm, and the
 * "I want to play a game" intro shown when a game starts.
 */
(function (global) {
  const sounds = () => global.RoomSounds;

  let glitchTimer = null;

  function glitch() {
    document.body.classList.remove("fx-glitch");
    void document.body.offsetWidth;
    document.body.classList.add("fx-glitch");
    if (glitchTimer) window.clearTimeout(glitchTimer);
    glitchTimer = window.setTimeout(() => {
      document.body.classList.remove("fx-glitch");
      glitchTimer = null;
    }, 600);
  }

  function setAlarm(on) {
    document.body.classList.toggle("fx-alarm", !!on);
  }

  const overlay = document.getElementById("intro-overlay");
  const textRoot = overlay ? overlay.querySelector(".crt-text") : null;

  const CHAR_MS = 22;
  const LINE_PAUSE_MS = 420;
  const AUTO_CLOSE_MS = 9000;
  // Leave the text finished a beat before the narration ends.
  const VOICE_TAIL_MS = 1500;
  const VOICE_FADE_MS = 400;

  const voice = overlay ? new Audio("/static/audio/intro.mp3?v=2") : null;
  if (voice) voice.preload = "auto";

  let charMs = CHAR_MS;
  let showToken = 0;
  let fadeFrame = null;
  let lines = [];
  let typing = false;
  let finished = false;
  let typeTimer = null;
  let autoCloseTimer = null;
  let shownFor = null;

  // Capture each line's text nodes once so typing preserves inline markup like <em>.
  if (textRoot) {
    lines = Array.from(textRoot.querySelectorAll("[data-type]")).map((el) => {
      const nodes = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        nodes.push({ node: walker.currentNode, full: walker.currentNode.nodeValue.replace(/\s+/g, " ") });
      }
      return { el, nodes };
    });
  }

  function clearTimers() {
    if (typeTimer) window.clearTimeout(typeTimer);
    if (autoCloseTimer) window.clearTimeout(autoCloseTimer);
    typeTimer = autoCloseTimer = null;
  }

  function resetText() {
    for (const line of lines) {
      line.el.classList.remove("typing");
      line.el.style.visibility = "hidden";
      for (const n of line.nodes) n.node.nodeValue = "";
    }
  }

  function revealAll() {
    for (const line of lines) {
      line.el.classList.remove("typing");
      line.el.style.visibility = "";
      for (const n of line.nodes) n.node.nodeValue = n.full;
    }
  }

  function voicePlaying() {
    return !!voice && !voice.paused && !voice.ended;
  }

  function voiceRemainingMs() {
    if (!voicePlaying() || !isFinite(voice.duration)) return 0;
    return Math.max(0, (voice.duration - voice.currentTime) * 1000);
  }

  function cancelVoiceFade() {
    if (fadeFrame) window.cancelAnimationFrame(fadeFrame);
    fadeFrame = null;
    if (voice) voice.volume = 1;
  }

  function stopVoice() {
    if (!voicePlaying()) return;
    cancelVoiceFade();
    const t0 = performance.now();
    function fade() {
      const k = Math.min(1, (performance.now() - t0) / VOICE_FADE_MS);
      voice.volume = 1 - k;
      if (k < 1) {
        fadeFrame = window.requestAnimationFrame(fade);
      } else {
        fadeFrame = null;
        voice.pause();
        voice.volume = 1;
      }
    }
    fade();
  }

  function totalChars() {
    return lines.reduce((sum, line) => sum + line.nodes.reduce((s, n) => s + n.full.length, 0), 0);
  }

  function paceToVoice(seconds) {
    const chars = totalChars();
    if (!chars || !isFinite(seconds)) return CHAR_MS;
    const typingMs = seconds * 1000 - VOICE_TAIL_MS - LINE_PAUSE_MS * Math.max(0, lines.length - 1);
    return Math.max(CHAR_MS, typingMs / chars);
  }

  function finish() {
    if (typeTimer) window.clearTimeout(typeTimer);
    typeTimer = null;
    typing = false;
    finished = true;
    revealAll();
    if (autoCloseTimer) window.clearTimeout(autoCloseTimer);
    autoCloseTimer = window.setTimeout(close, AUTO_CLOSE_MS + voiceRemainingMs());
  }

  function typeLines() {
    typing = true;
    let li = 0;
    let ni = 0;
    let ci = 0;
    let tick = 0;
    function step() {
      if (li >= lines.length) {
        finish();
        return;
      }
      const line = lines[li];
      line.el.style.visibility = "";
      line.el.classList.add("typing");
      const n = line.nodes[ni];
      if (!n) {
        line.el.classList.remove("typing");
        li += 1;
        ni = 0;
        ci = 0;
        typeTimer = window.setTimeout(step, LINE_PAUSE_MS);
        return;
      }
      ci += 1;
      n.node.nodeValue = n.full.slice(0, ci);
      tick += 1;
      if (tick % 3 === 0 && n.full[ci - 1] !== " " && sounds()) sounds().typeTick();
      if (ci >= n.full.length) {
        ni += 1;
        ci = 0;
      }
      typeTimer = window.setTimeout(step, charMs);
    }
    step();
  }

  function close() {
    if (!overlay || overlay.hidden) return;
    clearTimers();
    showToken += 1;
    stopVoice();
    typing = false;
    overlay.classList.add("closing");
    window.setTimeout(() => {
      overlay.hidden = true;
      overlay.classList.remove("closing");
      revealAll();
    }, 450);
  }

  function show(opts) {
    if (!overlay || !textRoot) return;
    const key = opts && opts.key;
    if (key && key === shownFor) return;
    shownFor = key || null;
    clearTimers();
    finished = false;
    overlay.classList.remove("closing");
    overlay.hidden = false;
    resetText();
    charMs = CHAR_MS;
    const token = ++showToken;

    const fallback = () => {
      if (token !== showToken) return;
      if (sounds()) sounds().drone(18);
      typeTimer = window.setTimeout(typeLines, 700);
    };
    if (!voice) {
      fallback();
      return;
    }
    // Autoplay can be refused if nobody has tapped this screen yet; fall back to the silent intro.
    cancelVoiceFade();
    voice.currentTime = 0;
    voice
      .play()
      .then(() => {
        if (token !== showToken) {
          voice.pause();
          return;
        }
        charMs = paceToVoice(voice.duration);
        if (sounds()) sounds().drone(isFinite(voice.duration) ? voice.duration : 18);
        typeTimer = window.setTimeout(typeLines, 300);
      })
      .catch(fallback);
  }

  if (overlay) {
    const advance = () => {
      if (typing) finish();
      else if (finished) close();
    };
    overlay.addEventListener("click", advance);
    document.addEventListener("keydown", (ev) => {
      if (overlay.hidden) return;
      if (ev.key === "Enter" || ev.key === " " || ev.key === "Escape") {
        ev.preventDefault();
        if (ev.key === "Escape") close();
        else advance();
      }
    });
  }

  global.RoomFx = {
    glitch,
    setAlarm,
    intro: { show, close },
  };
})(window);
