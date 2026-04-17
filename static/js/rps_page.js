(function () {
  const btnStart = document.getElementById("btn-start");
  const diffSel = document.getElementById("difficulty");
  const statusEl = document.getElementById("status");
  const scoreYou = document.getElementById("score-you");
  const scoreGm = document.getElementById("score-gm");
  const roundI = document.getElementById("round-i");
  const reveal = document.getElementById("reveal");
  const timerInner = document.querySelector(".timer-bar > i");
  const choiceBtns = Array.from(document.querySelectorAll(".rps-choice"));

  let ws = null;
  let pingTimer = null;
  let animFrame = null;
  let canPlay = false;

  const ICONS = { rock: "✊", paper: "✋", scissors: "✌️" };

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

  function setChoicesEnabled(on) {
    canPlay = on;
    for (const b of choiceBtns) b.disabled = !on;
  }

  function stopTimerAnim() {
    if (animFrame) cancelAnimationFrame(animFrame);
    animFrame = null;
    if (timerInner) timerInner.style.transform = "scaleX(0)";
  }

  function runTimerBar(windowMs) {
    stopTimerAnim();
    const deadline = performance.now() + windowMs;
    const tick = () => {
      const left = deadline - performance.now();
      const t = Math.max(0, left / windowMs);
      if (timerInner) timerInner.style.transform = "scaleX(" + t + ")";
      if (left > 0) animFrame = requestAnimationFrame(tick);
    };
    animFrame = requestAnimationFrame(tick);
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
    ws = new WebSocket(proto + "://" + location.host + "/ws/minigame/rps");
    ws.addEventListener("open", wirePing);
    ws.addEventListener("message", (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "started") {
        scoreYou.textContent = "0";
        scoreGm.textContent = "0";
        roundI.textContent = "–";
        setStatus("Match on — first to " + msg.win_target + ".", "");
        btnStart.disabled = true;
        reveal.className = "rps-reveal muted";
        reveal.textContent = "Waiting for first round…";
        return;
      }
      if (msg.type === "round") {
        roundI.textContent = String(msg.index);
        scoreYou.textContent = String(msg.score.player);
        scoreGm.textContent = String(msg.score.gm);
        setStatus("Pick one — you have " + Math.round(msg.turn_timeout_ms / 100) / 10 + "s.", "good");
        runTimerBar(msg.turn_timeout_ms);
        reveal.className = "rps-reveal muted";
        reveal.innerHTML = "Make your move…";
        setChoicesEnabled(true);
        return;
      }
      if (msg.type === "reveal") {
        stopTimerAnim();
        setChoicesEnabled(false);
        scoreYou.textContent = String(msg.score.player);
        scoreGm.textContent = String(msg.score.gm);
        const you = msg.player ? ICONS[msg.player] + " " + msg.player : "— no pick";
        const gm = ICONS[msg.gm] + " " + msg.gm;
        const outcome = msg.outcome;
        reveal.className = "rps-reveal " + outcome;
        const label = outcome === "win" ? "You win!" : outcome === "lose" ? "Gamemaster wins." : "Tie.";
        reveal.innerHTML =
          "<span>You: <strong>" + you + "</strong></span>" +
          "<span>GM: <strong>" + gm + "</strong></span>" +
          '<span class="outcome">' + label + "</span>";
        sfx("rpsReveal", outcome);
        return;
      }
      if (msg.type === "over") {
        stopTimerAnim();
        setChoicesEnabled(false);
        btnStart.disabled = false;
        setStatus(msg.won ? "You took the match!" : "Gamemaster wins the match.", msg.won ? "good" : "bad");
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
      stopTimerAnim();
      setChoicesEnabled(false);
      btnStart.disabled = false;
    });
  }

  for (const b of choiceBtns) {
    b.addEventListener("click", () => {
      if (!canPlay || !ws || ws.readyState !== WebSocket.OPEN) return;
      if (window.MinigameSounds) window.MinigameSounds.resume();
      ws.send(JSON.stringify({ action: "play", choice: b.dataset.choice }));
      setChoicesEnabled(false);
      setStatus("Locked in: " + b.dataset.choice, "");
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

  setChoicesEnabled(false);
  document.addEventListener("DOMContentLoaded", () => ensureWs());
})();
