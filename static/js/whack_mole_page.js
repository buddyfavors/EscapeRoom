(function () {
  const gridRoot = document.getElementById("arcade-root");
  const btnStart = document.getElementById("btn-start");
  const diffSel = document.getElementById("difficulty");
  const statusEl = document.getElementById("status");
  const logEl = document.getElementById("log");
  const timerInner = document.querySelector(".timer-bar > i");

  let ws = null;
  let pingTimer = null;
  let roundWindowMs = 2800;
  let roundDeadline = 0;
  let animFrame = null;

  function sfx(name) {
    try {
      const S = window.MinigameSounds;
      if (S && typeof S[name] === "function") S[name]();
    } catch (e) {
      /* ignore */
    }
  }

  const grid = window.mountArcadeGrid(gridRoot, (id) => {
    if (window.MinigameSounds) window.MinigameSounds.resume();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "hit", button: id }));
    }
  });

  function setStatus(text, tone) {
    statusEl.textContent = text;
    statusEl.className = "status-pill";
    if (tone === "bad") statusEl.classList.add("bad");
    if (tone === "good") statusEl.classList.add("good");
  }

  function log(msg) {
    logEl.innerHTML = msg;
  }

  function stopTimerAnim() {
    if (animFrame) cancelAnimationFrame(animFrame);
    animFrame = null;
    if (timerInner) timerInner.style.transform = "scaleX(0)";
  }

  function runRoundTimer() {
    stopTimerAnim();
    roundDeadline = performance.now() + roundWindowMs;
    const tick = () => {
      const left = roundDeadline - performance.now();
      const t = Math.max(0, left / roundWindowMs);
      if (timerInner) timerInner.style.transform = "scaleX(" + t + ")";
      if (left > 0) animFrame = requestAnimationFrame(tick);
    };
    animFrame = requestAnimationFrame(tick);
  }

  function wirePing() {
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: "ping" }));
      }
    }, 20000);
  }

  function ensureWs() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(proto + "://" + location.host + "/ws/minigame/whack-mole");
    ws.addEventListener("open", () => {
      wirePing();
    });
    ws.addEventListener("message", (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "started") {
        roundWindowMs = +msg.round_window_ms || 2800;
        setStatus("Only hit glowing SAFE moles.", "good");
        log(
          "<strong>" +
            msg.rounds +
            "</strong> rounds · Clear all safe moles before time · Traps cost a life · Win by clearing ~55% of rounds with lives left."
        );
        grid.clearAll();
        btnStart.disabled = true;
        return;
      }
      if (msg.type === "round") {
        grid.setWhackMoles(msg.moles);
        setStatus("Round " + msg.index + " — safe only!", "good");
        log("Score <strong>" + msg.score + "</strong> · Lives <strong>" + msg.lives + "</strong>");
        runRoundTimer();
        sfx("whackRound");
        return;
      }
      if (msg.type === "safe_hit") {
        setStatus("Good hit.", "good");
        sfx("whackSafeTap");
        return;
      }
      if (msg.type === "trap_hit") {
        setStatus("Trap!", "bad");
        log(msg.message || "");
        grid.clearAll();
        stopTimerAnim();
        sfx("whackTrap");
        return;
      }
      if (msg.type === "round_clear") {
        setStatus("Round cleared!", "good");
        log("Score <strong>" + msg.score + "</strong>");
        grid.clearAll();
        stopTimerAnim();
        sfx("whackRoundClear");
        return;
      }
      if (msg.type === "round_timeout") {
        setStatus("Time!", "bad");
        log(msg.message || "");
        grid.clearAll();
        stopTimerAnim();
        sfx("whackTimeout");
        return;
      }
      if (msg.type === "over") {
        grid.clearAll();
        stopTimerAnim();
        setStatus(msg.won ? "Crew wins!" : "Gamemaster wins.", msg.won ? "good" : "bad");
        sfx(msg.won ? "whackWin" : "whackLose");
        log(
          "Score <strong>" +
            msg.score +
            "</strong> (needed <strong>" +
            (msg.cleared_needed || "?") +
            "</strong>) · Lives <strong>" +
            msg.lives +
            "</strong>"
        );
        btnStart.disabled = false;
        return;
      }
      if (msg.type === "error") {
        log(msg.message || "Error");
        btnStart.disabled = false;
      }
    });
    ws.addEventListener("close", () => {
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = null;
      stopTimerAnim();
      btnStart.disabled = false;
    });
  }

  btnStart.addEventListener("click", () => {
    if (window.MinigameSounds) window.MinigameSounds.resume();
    ensureWs();
    const startPayload = JSON.stringify({ action: "start", difficulty: diffSel.value });
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(startPayload);
      return;
    }
    ws.addEventListener(
      "open",
      () => {
        ws.send(startPayload);
      },
      { once: true }
    );
  });

  document.addEventListener("DOMContentLoaded", () => ensureWs());
})();
