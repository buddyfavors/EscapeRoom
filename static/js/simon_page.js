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
    const col = Math.floor(id / 3);
    sfx("simonTone", col);
    ws.send(JSON.stringify({ action: "press", button: id, column: col }));
  });

  async function playSequence(sequence, stepMs) {
    inputOpen = false;
    grid.clearAll();
    setStatus("Watch…", "");
    const hold = Math.max(160, Math.min(800, stepMs));
    for (const col of sequence) {
      sfx("simonTone", col);
      await grid.flashColumn(col, hold);
      await new Promise((r) => setTimeout(r, Math.max(80, hold * 0.25)));
    }
    inputOpen = true;
    setStatus("Your turn — repeat it.", "good");
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
    ws = new WebSocket(proto + "://" + location.host + "/ws/minigame/simon");
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
      if (msg.type === "play_sequence") {
        log("Round <strong>" + msg.round + "</strong> · length <strong>" + msg.sequence.length + "</strong> · lives <strong>" + msg.lives + "</strong>");
        playSequence(msg.sequence, msg.step_ms);
        return;
      }
      if (msg.type === "press") {
        const id = Math.max(0, Math.min(14, msg.column * 3 + 1));
        grid.pulseButton(id, msg.correct ? "correct" : "incorrect", 350);
        if (!msg.correct) {
          inputOpen = false;
          setStatus("Wrong press!", "bad");
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
        log("Cleared <strong>" + msg.cleared + "</strong> · next length " + (msg.length + 1));
        sfx("genericOk");
        return;
      }
      if (msg.type === "over") {
        inputOpen = false;
        grid.clearAll();
        btnStart.disabled = false;
        setStatus(msg.won ? "You beat the Gamemaster." : "Gamemaster wins.", msg.won ? "good" : "bad");
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
