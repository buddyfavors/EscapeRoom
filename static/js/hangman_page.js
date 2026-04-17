(function () {
  const btnStart = document.getElementById("btn-start");
  const diffSel = document.getElementById("difficulty");
  const statusEl = document.getElementById("status");
  const wordEl = document.getElementById("word");
  const keyboardEl = document.getElementById("keyboard");
  const livesEl = document.getElementById("lives");
  const logEl = document.getElementById("log");

  let ws = null;
  let pingTimer = null;
  let keyBtns = new Map();
  let inputOpen = false;
  let maxWrong = 6;

  function sfx(name) {
    try {
      const S = window.MinigameSounds;
      if (S && typeof S[name] === "function") S[name]();
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

  function renderKeyboard() {
    keyboardEl.innerHTML = "";
    keyBtns.clear();
    const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    for (const ch of letters) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "hangman-key";
      b.textContent = ch;
      b.disabled = true;
      b.addEventListener("click", () => {
        if (!inputOpen || !ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({ action: "guess", letter: ch }));
      });
      keyBtns.set(ch, b);
      keyboardEl.appendChild(b);
    }
  }

  function setKeyboardEnabled(on) {
    inputOpen = on;
    for (const b of keyBtns.values()) {
      if (b.classList.contains("hit") || b.classList.contains("miss")) continue;
      b.disabled = !on;
    }
  }

  function renderWord(mask) {
    wordEl.innerHTML = "";
    for (const ch of mask || []) {
      const s = document.createElement("div");
      s.className = "hangman-slot" + (ch ? " filled" : "");
      s.textContent = ch || "";
      wordEl.appendChild(s);
    }
  }

  function renderLives(wrong) {
    livesEl.innerHTML = "";
    const left = Math.max(0, maxWrong - wrong);
    for (let i = 0; i < maxWrong; i++) {
      const d = document.createElement("span");
      d.className = "hangman-life " + (i < left ? "alive" : "lost");
      livesEl.appendChild(d);
    }
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
    ws = new WebSocket(proto + "://" + location.host + "/ws/minigame/hangman");
    ws.addEventListener("open", wirePing);
    ws.addEventListener("message", (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "started") {
        maxWrong = msg.max_wrong;
        renderKeyboard();
        setKeyboardEnabled(true);
        renderWord(msg.mask);
        renderLives(0);
        setStatus("Guess letters.", "good");
        log("Word length <strong>" + msg.length + "</strong> · " + msg.max_wrong + " wrong allowed");
        btnStart.disabled = true;
        return;
      }
      if (msg.type === "result") {
        const b = keyBtns.get(msg.letter);
        if (b) {
          b.classList.add(msg.hit ? "hit" : "miss");
          b.disabled = true;
        }
        renderWord(msg.mask);
        renderLives(msg.wrong);
        setStatus(msg.hit ? "Hit!" : "Miss — " + (msg.max_wrong - msg.wrong) + " left.", msg.hit ? "good" : "bad");
        sfx(msg.hit ? "genericOk" : "genericWrong");
        return;
      }
      if (msg.type === "repeat") {
        setStatus("Already guessed " + msg.letter + ".", "");
        return;
      }
      if (msg.type === "timeout") {
        renderWord(msg.mask);
        renderLives(msg.wrong);
        setStatus("Too slow — lost a life.", "bad");
        sfx("genericWrong");
        return;
      }
      if (msg.type === "over") {
        setKeyboardEnabled(false);
        btnStart.disabled = false;
        if (msg.won) {
          setStatus("You found the word: " + msg.word, "good");
          sfx("genericWin");
        } else {
          setStatus("Gamemaster wins. Word was: " + msg.word, "bad");
          sfx("genericLose");
          renderWord(Array.from(msg.word));
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
      setKeyboardEnabled(false);
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

  renderKeyboard();
  renderLives(0);
  renderWord([null, null, null, null, null]);
  document.addEventListener("DOMContentLoaded", () => ensureWs());
})();
