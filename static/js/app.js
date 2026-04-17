const banner = document.getElementById("banner");
const locksEl = document.getElementById("locks");
const btnPlay = document.getElementById("btn-play");
const overviewView = document.getElementById("overview-view");
const activeView = document.getElementById("active-view");
const activeDifficulty = document.getElementById("active-difficulty");
const progressPill = document.getElementById("progress-pill");
const wonBadge = document.getElementById("won-badge");
const strikePill = document.getElementById("strike-pill");
const strikeDots = document.getElementById("strike-dots");
const strikeCount = document.getElementById("strike-count");

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
  if (!clues.length) return '<span class="muted">No clues yet.</span>';
  const parts = clues.map((c) => {
    const ch = c == null || c === "" ? "·" : String(c);
    const cls = c == null || c === "" ? "clue-cell empty" : "clue-cell filled";
    return `<span class="${cls}">${ch}</span>`;
  });
  return `<span class="clue-row">${parts.join("")}</span>`;
}

function lockStateLabel(lock) {
  if (lock.solved) return "OPEN";
  if (lock.fully_revealed) return "CODE REVEALED";
  return "LOCKED";
}

function renderStrikes(snap) {
  if (!strikePill) return;
  const threshold = Math.max(1, Number(snap && snap.bad_streak_threshold) || 2);
  const current = Math.max(0, Number(snap && snap.bad_streak) || 0);
  if (strikeCount) strikeCount.textContent = `${current} / ${threshold}`;
  if (strikeDots) {
    const dots = [];
    for (let i = 0; i < threshold; i += 1) {
      const lit = i < current ? "lit" : "";
      dots.push(`<span class="strike-dot ${lit}"></span>`);
    }
    strikeDots.innerHTML = dots.join("");
  }
  strikePill.classList.toggle("danger", current > 0 && current >= threshold - 1);
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
    renderStrikes(null);
    return;
  }
  renderStrikes(snap);
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
  if (wonBadge) {
    const escaped = snap.won === true || snap.won === "true";
    wonBadge.hidden = !escaped;
  }
  locksEl.innerHTML = "";
  for (const lock of snap.locks) {
    const card = document.createElement("div");
    const classes = ["lock-card"];
    if (lock.solved) classes.push("solved");
    else if (lock.fully_revealed) classes.push("revealed");
    card.className = classes.join(" ");
    card.innerHTML = `
      <div class="lock-kind">${kindLabel(lock.kind)}</div>
      <div class="lock-state">${lockStateLabel(lock)}</div>
      <div class="lock-clues">${formatClues(lock)}</div>
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
    const tone = msg.reason === "good_scan_bonus" ? "ok" : "bad";
    const text =
      msg.message ||
      (msg.reason === "good_scan_bonus"
        ? "The Gamemaster smiles — a bonus challenge before you continue."
        : "The Gamemaster locks the room — a minigame begins…");
    setBanner(text, tone);
    window.setTimeout(() => {
      window.location.href = msg.url;
    }, 1200);
    return;
  }
  if (msg.type === "punishment_text") {
    setBanner("Punishment: " + (msg.message || "The Gamemaster claims this one."), "bad");
    return;
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
