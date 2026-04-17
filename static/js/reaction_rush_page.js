(function () {
  const gridRoot = document.getElementById("arcade-root");
  const btnStart = document.getElementById("btn-start");
  const diffSel = document.getElementById("difficulty");
  const statusEl = document.getElementById("status");
  const logEl = document.getElementById("log");
  const timerInner = document.querySelector(".timer-bar > i");

  let ws = null;
  let pingTimer = null;
  let deadlineTs = 0;
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

  function runTimerBar(windowMs) {
    stopTimerAnim();
    deadlineTs = performance.now() + windowMs;
    const tick = () => {
      const left = deadlineTs - performance.now();
      const t = Math.max(0, left / windowMs);
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
    ws = new WebSocket(proto + "://" + location.host + "/ws/minigame/reaction-rush");
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
        setStatus("Go when the board lights!", "");
        log("Win at <strong>" + msg.win_score + "</strong> hits · Lives <strong>" + msg.lives + "</strong>");
        grid.clearAll();
        btnStart.disabled = true;
        return;
      }
      if (msg.type === "go") {
        grid.setReactionTarget(msg.target);
        setStatus("Hit " + (msg.color || "") + " · slot " + ((msg.target % 3) + 1), "good");
        runTimerBar(+msg.window_ms || 1000);
        sfx("reactionGo");
        return;
      }
      if (msg.type === "hit_ok") {
        setStatus("Nice! Score " + msg.score, "good");
        log("Next window ~<strong>" + Math.round(msg.window_ms) + "ms</strong>");
        sfx("reactionHit");
        return;
      }
      if (msg.type === "miss") {
        setStatus(msg.reason === "timeout" ? "Too slow!" : "Wrong button!", "bad");
        log("Lives left: <strong>" + msg.lives + "</strong>");
        grid.clearAll();
        stopTimerAnim();
        sfx("reactionMiss");
        return;
      }
      if (msg.type === "over") {
        stopTimerAnim();
        grid.clearAll();
        setStatus(msg.won ? "You beat the clock!" : "The Gamemaster wins this round.", msg.won ? "good" : "bad");
        log(msg.won ? "Final score <strong>" + msg.score + "</strong>" : "Try again when ready.");
        btnStart.disabled = false;
        sfx(msg.won ? "reactionWin" : "reactionLose");
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
