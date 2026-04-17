const banner = document.getElementById("banner");
const locksEl = document.getElementById("locks");
const btnPlay = document.getElementById("btn-play");
const btnStop = document.getElementById("btn-stop");
const mgList = document.getElementById("minigames");
const formTest = document.getElementById("form-test");
const testCode = document.getElementById("test-code");

function selectedDifficulty() {
  const el = document.querySelector('input[name="difficulty"]:checked');
  return el ? el.value : "easy";
}

function kindLabel(kind) {
  if (kind === "digit3") return "3-digit lock";
  if (kind === "digit4") return "4-digit lockbox";
  if (kind === "letter5") return "5-letter lock";
  return kind;
}

function formatClues(lock) {
  const clues = lock.clues || [];
  if (!clues.length) return "No clues yet.";
  return clues.map((c) => (c == null || c === "" ? "·" : String(c))).join(" ");
}

function renderSnapshot(snap) {
  locksEl.innerHTML = "";
  if (!snap || !snap.locks) {
    locksEl.textContent = "No active game.";
    return;
  }
  for (const lock of snap.locks) {
    const card = document.createElement("div");
    card.className = "lock-card" + (lock.solved ? " solved" : "");
    card.innerHTML = `
      <div class="lock-kind">${kindLabel(lock.kind)}</div>
      <div class="lock-state">${lock.solved ? "OPEN" : "LOCKED"}</div>
      <div class="lock-clues muted">${formatClues(lock)}</div>
    `;
    locksEl.appendChild(card);
  }
}

function setBanner(text, tone) {
  banner.textContent = text || "";
  banner.classList.remove("ok", "bad");
  if (tone === "ok") banner.classList.add("ok");
  if (tone === "bad") banner.classList.add("bad");
}

function bannerToneForResult(r) {
  const inter = r.interaction || "lock";
  if (inter === "rfid_exhausted") return "";
  if (inter === "rfid_hint" && r.ok) return "ok";
  return r.ok ? "ok" : "bad";
}

async function postJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

btnPlay.addEventListener("click", async () => {
  btnPlay.disabled = true;
  try {
    const data = await postJson("/api/game/start", { difficulty: selectedDifficulty() });
    setBanner("Game started. Good luck!", "ok");
    renderSnapshot(data.snapshot);
  } catch (e) {
    setBanner(String(e.message || e), "bad");
  } finally {
    btnPlay.disabled = false;
  }
});

btnStop.addEventListener("click", async () => {
  try {
    await postJson("/api/game/stop", {});
    setBanner("Game ended.", "");
    renderSnapshot(null);
  } catch (e) {
    setBanner(String(e.message || e), "bad");
  }
});

formTest.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const code = testCode.value || "";
  try {
    const data = await postJson("/api/game/submit", { code });
    if (data.snapshot) renderSnapshot(data.snapshot);
    setBanner(data.result.message, bannerToneForResult(data.result));
  } catch (e) {
    setBanner(String(e.message || e), "bad");
  }
});

function applyWsMessage(msg) {
  if (msg.type === "hello") {
    renderSnapshot(msg.snapshot);
    return;
  }
  if (msg.type === "game_started" || msg.type === "code_result") {
    if (msg.snapshot) renderSnapshot(msg.snapshot);
    if (msg.type === "code_result" && msg.result) {
      setBanner(msg.result.message, bannerToneForResult(msg.result));
    }
    return;
  }
  if (msg.type === "game_stopped") {
    renderSnapshot(null);
    setBanner("Game ended.", "");
  }
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  let pingTimer = null;
  ws.addEventListener("message", (ev) => {
    try {
      applyWsMessage(JSON.parse(ev.data));
    } catch {
      /* ignore */
    }
  });
  ws.addEventListener("open", () => {
    if (pingTimer) window.clearInterval(pingTimer);
    pingTimer = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 25000);
  });
  ws.addEventListener("close", () => {
    if (pingTimer) window.clearInterval(pingTimer);
    pingTimer = null;
    window.setTimeout(connectWs, 1200);
  });
}

async function loadMinigames() {
  const res = await fetch("/api/minigames");
  const items = await res.json();
  const skip = new Set(["reaction", "whack_a_mole"]);
  mgList.innerHTML = "";
  for (const m of items) {
    if (skip.has(m.id)) continue;
    const li = document.createElement("li");
    li.innerHTML = `<strong>${m.title}</strong> — ${m.description}`;
    mgList.appendChild(li);
  }
}

(async () => {
  try {
    const res = await fetch("/api/game/status");
    const data = await res.json();
    if (data.snapshot) renderSnapshot(data.snapshot);
  } catch {
    /* offline */
  }
  connectWs();
  loadMinigames();
})();
