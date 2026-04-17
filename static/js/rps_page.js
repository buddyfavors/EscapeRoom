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

  const ROUND_STYLE_CLASSES = [
    "rps-pick-you",
    "rps-pick-gm",
    "rps-result-win",
    "rps-result-lose",
    "rps-result-tie",
    "rps-gm-round-win",
    "rps-round-timeout",
  ];

  function clearRpsRoundStyles() {
    for (const b of choiceBtns) {
      for (const cls of ROUND_STYLE_CLASSES) b.classList.remove(cls);
    }
  }

  function applyRpsRevealStyles(msg) {
    clearRpsRoundStyles();
    if (!msg.gm) return;
    if (msg.reason === "timeout" || !msg.player) {
      for (const b of choiceBtns) b.classList.add("rps-round-timeout");
      const gmBtn = choiceBtns.find((x) => x.dataset.choice === msg.gm);
      if (gmBtn) gmBtn.classList.add("rps-pick-gm", "rps-gm-round-win");
      return;
    }
    const p = msg.player;
    const g = msg.gm;
    const o = msg.outcome;
    for (const b of choiceBtns) {
      const c = b.dataset.choice;
      if (c === p) b.classList.add("rps-pick-you");
      if (c === g) b.classList.add("rps-pick-gm");
    }
    if (o === "tie") {
      const b = choiceBtns.find((x) => x.dataset.choice === p);
      if (b) b.classList.add("rps-result-tie");
      return;
    }
    const youBtn = choiceBtns.find((x) => x.dataset.choice === p);
    const gmBtn = choiceBtns.find((x) => x.dataset.choice === g);
    if (o === "win" && youBtn) youBtn.classList.add("rps-result-win");
    if (o === "lose" && youBtn) youBtn.classList.add("rps-result-lose");
    if (o === "lose" && gmBtn) gmBtn.classList.add("rps-gm-round-win");
  }

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
        clearRpsRoundStyles();
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
        clearRpsRoundStyles();
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
        applyRpsRevealStyles(msg);
        scoreYou.textContent = String(msg.score.player);
        scoreGm.textContent = String(msg.score.gm);
        const you = msg.player ? ICONS[msg.player] + " " + msg.player : "— no pick (timeout)";
        const gm = ICONS[msg.gm] + " " + msg.gm;
        const outcome = msg.outcome;
        reveal.className = "rps-reveal " + outcome;
        const label =
          msg.reason === "timeout"
            ? "Timeout — GM scores."
            : outcome === "win"
              ? "You win the throw!"
              : outcome === "lose"
                ? "Gamemaster wins the throw."
                : "Tie.";
        reveal.innerHTML =
          "<span>You: <strong>" + you + "</strong></span>" +
          "<span>GM: <strong>" + gm + "</strong></span>" +
          '<span class="outcome">' + label + "</span>";
        const stTone = outcome === "win" ? "good" : outcome === "lose" || msg.reason === "timeout" ? "bad" : "";
        setStatus("Result on the buttons — next round in a moment.", stTone);
        sfx("rpsReveal", outcome);
        return;
      }
      if (msg.type === "over") {
        stopTimerAnim();
        clearRpsRoundStyles();
        setChoicesEnabled(false);
        btnStart.disabled = false;
        setStatus(msg.won ? "You took the match!" : "Gamemaster wins the match.", msg.won ? "good" : "bad");
        sfx(msg.won ? "genericWin" : "genericLose");
        if (window.MinigameReturn && window.MinigameReturn.isForced()) {
          window.MinigameReturn.scheduleReturn({
            seconds: 60,
            headline: msg.won ? "You beat the Gamemaster at RPS." : "RPS: the Gamemaster won.",
          });
        }
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
