(function () {
  const gridRoot = document.getElementById("arcade-root");
  const btnStart = document.getElementById("btn-start");
  const diffSel = document.getElementById("difficulty");
  const statusEl = document.getElementById("status");
  const logEl = document.getElementById("log");

  let ws = null;
  let pingTimer = null;
  let inputOpen = false;

  function sfx(name, arg) {
    try {
      const S = window.MinigameSounds;
      if (S && typeof S[name] === "function") S[name](arg);
    } catch {
      /* ignore */
    }
  }

  function setStatus(text, tone) {
    statusEl.textContent = text;
    statusEl.className = "status-pill";
    if (tone === "bad") statusEl.classList.add("bad");
    if (tone === "good") statusEl.classList.add("good");
  }

  function log(msg) {
    logEl.innerHTML = msg;
  }

  const grid = window.mountArcadeGrid(gridRoot, (id) => {
    if (!inputOpen || !ws || ws.readyState !== WebSocket.OPEN) return;
    if (window.MinigameSounds) window.MinigameSounds.resume();
    sfx("simonTone", Math.floor(id / 3));
    ws.send(JSON.stringify({ action: "press", button: id }));
  });

  async function showPattern(pattern, stepMs) {
    inputOpen = false;
    grid.clearAll();
    setStatus("Watch the pattern…", "");
    const hold = Math.max(180, Math.min(800, stepMs));
    for (const step of pattern) {
      sfx("simonTone", Math.floor(step.i / 3));
      await grid.flashButton(step.i, hold);
      await new Promise((r) => setTimeout(r, Math.max(80, hold * 0.25)));
    }
    inputOpen = true;
    setStatus("Repeat it — exact buttons, in order.", "good");
  }

  function wirePing() {
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: "ping" }));
    }, 20000);
  }

  function ensureWs() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(proto + "://" + location.host + "/ws/minigame/pattern");
    ws.addEventListener("open", wirePing);
    ws.addEventListener("message", (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "started") {
        btnStart.disabled = true;
        setStatus("Match on · win at " + msg.win_rounds + " rounds.", "");
        log("Lives <strong>" + msg.lives + "</strong>");
        return;
      }
      if (msg.type === "show_pattern") {
        log("Round <strong>" + msg.round + "</strong> · length <strong>" + msg.length + "</strong> · lives <strong>" + msg.lives + "</strong>");
        showPattern(msg.pattern, msg.step_ms);
        return;
      }
      if (msg.type === "press") {
        grid.pulseButton(msg.button, msg.correct ? "correct" : "incorrect", 350);
        if (!msg.correct) {
          inputOpen = false;
          setStatus("Wrong button!", "bad");
          sfx("genericWrong");
        }
        return;
      }
      if (msg.type === "timeout") {
        inputOpen = false;
        setStatus("Too slow.", "bad");
        sfx("genericWrong");
        return;
      }
      if (msg.type === "round_failed") {
        inputOpen = false;
        log("Round failed. Lives <strong>" + msg.lives + "</strong>");
        return;
      }
      if (msg.type === "round_clear") {
        inputOpen = false;
        setStatus("Clean round!", "good");
        log("Cleared <strong>" + msg.cleared + "</strong> · length next " + (msg.length + 1));
        sfx("genericOk");
        return;
      }
      if (msg.type === "over") {
        inputOpen = false;
        grid.clearAll();
        btnStart.disabled = false;
        setStatus(msg.won ? "You cracked the pattern!" : "Gamemaster wins.", msg.won ? "good" : "bad");
        log("Rounds cleared <strong>" + msg.cleared + "</strong>");
        sfx(msg.won ? "genericWin" : "genericLose");
        return;
      }
      if (msg.type === "error") {
        setStatus(msg.message || "Error", "bad");
        btnStart.disabled = false;
      }
    });
    ws.addEventListener("close", () => {
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = null;
      inputOpen = false;
      btnStart.disabled = false;
    });
  }

  btnStart.addEventListener("click", () => {
    if (window.MinigameSounds) window.MinigameSounds.resume();
    ensureWs();
    const payload = JSON.stringify({ action: "start", difficulty: diffSel.value });
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(payload);
      return;
    }
    ws.addEventListener("open", () => ws.send(payload), { once: true });
  });

  document.addEventListener("DOMContentLoaded", () => ensureWs());
})();
