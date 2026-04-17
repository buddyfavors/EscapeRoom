const banner = document.getElementById("banner");
const locksEl = document.getElementById("locks");
const btnPlay = document.getElementById("btn-play");
const overviewView = document.getElementById("overview-view");
const activeView = document.getElementById("active-view");
const activeDifficulty = document.getElementById("active-difficulty");
const progressPill = document.getElementById("progress-pill");
const wonBadge = document.getElementById("won-badge");

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

function setActiveView(snap) {
  const active = !!(snap && snap.locks);
  if (overviewView) overviewView.hidden = active;
  if (activeView) activeView.hidden = !active;
  if (window.NavSetGameActive) window.NavSetGameActive(active);
  if (!active) {
    if (locksEl) locksEl.innerHTML = "";
    if (progressPill) progressPill.textContent = "0 / 0 open";
    if (wonBadge) wonBadge.hidden = true;
    return;
  }
  if (activeDifficulty) {
    const d = (snap.difficulty || "").toString();
    activeDifficulty.textContent = d ? "— " + d[0].toUpperCase() + d.slice(1) : "";
  }
  const total = snap.locks.length;
  const opened = snap.locks.filter((l) => l.solved).length;
  if (progressPill) {
    progressPill.textContent = opened + " / " + total + " open";
    progressPill.classList.toggle("good", opened === total && total > 0);
  }
  if (wonBadge) wonBadge.hidden = !snap.won;
  locksEl.innerHTML = "";
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
  if (!banner) return;
  banner.textContent = text || "";
  banner.classList.remove("ok", "bad");
  if (tone === "ok") banner.classList.add("ok");
  if (tone === "bad") banner.classList.add("bad");
}

function bannerToneForResult(r) {
  const inter = r.interaction || "lock";
  if (inter === "rfid_exhausted") return "";
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

if (btnPlay) {
  btnPlay.addEventListener("click", async () => {
    btnPlay.disabled = true;
    try {
      const data = await postJson("/api/game/start", { difficulty: selectedDifficulty() });
      setBanner("Game started. Good luck!", "ok");
      setActiveView(data.snapshot);
    } catch (e) {
      setBanner(String(e.message || e), "bad");
    } finally {
      btnPlay.disabled = false;
    }
  });
}

function applyWsMessage(msg) {
  if (msg.type === "hello") {
    setActiveView(msg.snapshot);
    return;
  }
  if (msg.type === "game_started" || msg.type === "code_result") {
    if (msg.snapshot) setActiveView(msg.snapshot);
    if (msg.type === "code_result" && msg.result) {
      setBanner(msg.result.message, bannerToneForResult(msg.result));
    }
    return;
  }
  if (msg.type === "game_stopped") {
    setActiveView(null);
    setBanner("Game ended.", "");
    return;
  }
  if (msg.type === "forced_minigame" && msg.url) {
    setBanner("The Gamemaster locks the room — a minigame begins…", "bad");
    window.setTimeout(() => {
      window.location.href = msg.url;
    }, 800);
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

(async () => {
  try {
    const res = await fetch("/api/game/status");
    const data = await res.json();
    setActiveView(data.snapshot);
  } catch {
    /* offline */
  }
  connectWs();
})();
