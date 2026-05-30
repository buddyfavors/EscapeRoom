const banner = document.getElementById("banner");
const locksEl = document.getElementById("locks");
const btnPlay = document.getElementById("btn-play");
const overviewView = document.getElementById("overview-view");
const activeView = document.getElementById("active-view");
const activeDifficulty = document.getElementById("active-difficulty");
const wonBadge = document.getElementById("won-badge");
const badCodesPill = document.getElementById("bad-codes-pill");
const badCodesDots = document.getElementById("bad-codes-dots");
const badCodesCount = document.getElementById("bad-codes-count");
const clueMinigamePill = document.getElementById("clue-minigame-pill");
const clueDots = document.getElementById("clue-dots");
const clueCount = document.getElementById("clue-count");
const punishmentsPill = document.getElementById("punishments-pill");
const punishmentsCount = document.getElementById("punishments-count");
const lastPunishmentEl = document.getElementById("last-punishment");
const gmWonBadge = document.getElementById("gm-won-badge");
const rfidNextBadEl = document.getElementById("rfid-next-bad");
const punishmentLimitInput = document.getElementById("punishment-limit");

const lockInputs = {
  digit3: document.getElementById("lock-digit3"),
  letter5: document.getElementById("lock-letter5"),
  digit4: document.getElementById("lock-digit4"),
};
const availLabels = {
  digit3: document.getElementById("avail-digit3"),
  letter5: document.getElementById("avail-letter5"),
  digit4: document.getElementById("avail-digit4"),
};
const gmPreviewEl = document.getElementById("gm-preview");

let setupData = null;
let previewTimer = null;

function lockPayload(counts) {
  return {
    digit3: counts.digit3,
    letter5: counts.letter5,
    digit4: counts.digit4,
  };
}

function renderGmPreview(programming, { loading = false, error = "" } = {}) {
  if (!gmPreviewEl) return;
  if (loading) {
    gmPreviewEl.innerHTML = "<p>Choosing combinations…</p>";
    gmPreviewEl.classList.add("muted");
    return;
  }
  if (error) {
    gmPreviewEl.innerHTML = `<p class="bad-text">${error}</p>`;
    gmPreviewEl.classList.add("muted");
    return;
  }
  if (!programming || !programming.length) {
    gmPreviewEl.innerHTML = "<p>Pick at least one lock to preview combinations.</p>";
    gmPreviewEl.classList.add("muted");
    return;
  }
  let html =
    `<p class="gm-meta"><strong>${programming.length}</strong> lock${programming.length === 1 ? "" : "s"} for this game</p>` +
    '<table class="gm-table"><thead><tr><th>#</th><th>Type</th><th>Set lock to</th></tr></thead><tbody>';
  for (const row of programming) {
    html += `<tr><td>${row.index}</td><td>${row.kind_label}</td><td class="gm-code">${row.code}</td></tr>`;
  }
  html += "</tbody></table>";
  gmPreviewEl.innerHTML = html;
  gmPreviewEl.classList.remove("muted");
}

function scheduleLockPreview() {
  if (previewTimer) window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => {
    previewTimer = null;
    refreshLockPreview();
  }, 350);
}

async function refreshLockPreview() {
  if (!gmPreviewEl || (overviewView && overviewView.hidden)) return;
  const locks = selectedLockCounts();
  if (locks.digit3 + locks.letter5 + locks.digit4 < 1) {
    renderGmPreview([]);
    return;
  }
  renderGmPreview([], { loading: true });
  try {
    const data = await postJson("/api/game/preview", lockPayload(locks));
    renderGmPreview(data.programming || []);
  } catch (e) {
    renderGmPreview([], { error: String(e.message || e) });
  }
}

function selectedPunishmentLimit() {
  const raw = punishmentLimitInput?.value || "3";
  const n = Math.max(1, Math.min(99, parseInt(raw, 10) || 3));
  if (punishmentLimitInput) punishmentLimitInput.value = String(n);
  return n;
}

function selectedDifficulty() {
  const el = document.querySelector('input[name="difficulty"]:checked');
  return el ? el.value : "medium";
}

function selectedLockCounts() {
  return {
    digit3: Math.max(0, parseInt(lockInputs.digit3?.value || "0", 10) || 0),
    letter5: Math.max(0, parseInt(lockInputs.letter5?.value || "0", 10) || 0),
    digit4: Math.max(0, parseInt(lockInputs.digit4?.value || "0", 10) || 0),
  };
}

function applySetup(data, { resetValues = false } = {}) {
  setupData = data;
  const available = data.available || {};
  const defaults = data.defaults || {};
  for (const kind of ["digit3", "letter5", "digit4"]) {
    const max = Math.max(0, Number(available[kind]) || 0);
    const input = lockInputs[kind];
    const label = availLabels[kind];
    if (input) {
      input.max = String(max);
      input.min = "0";
      if (resetValues) {
        const def = Number(defaults[kind]);
        const val = Number.isFinite(def) ? Math.min(def, max) : 0;
        input.value = String(val);
      } else {
        const current = Math.max(0, parseInt(input.value, 10) || 0);
        input.value = String(Math.min(current, max));
      }
      input.disabled = max === 0;
    }
    if (label) {
      if (max === 0) {
        label.textContent = "none available";
      } else if (max === 1) {
        label.textContent = "max 1";
      } else {
        label.textContent = `max ${max}`;
      }
    }
  }
  if (punishmentLimitInput && data.default_punishment_limit != null) {
    punishmentLimitInput.value = String(data.default_punishment_limit);
  }
}

async function loadSetup() {
  const embedded = document.getElementById("lock-setup-data");
  if (embedded && embedded.textContent) {
    try {
      applySetup(JSON.parse(embedded.textContent), { resetValues: true });
    } catch {
      /* ignore malformed embed */
    }
  }
  try {
    const res = await fetch("/api/game/setup");
    if (!res.ok) return;
    const data = await res.json();
    applySetup(data, { resetValues: false });
  } catch {
    /* keep server-rendered values */
  }
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

function renderBadCodesMeter(snap) {
  if (!badCodesPill) return;
  const goal = Math.max(1, Number(snap && snap.bad_codes_goal) || 3);
  const current = Math.max(0, Math.min(goal, Number(snap && snap.bad_codes_progress) || 0));
  if (badCodesCount) badCodesCount.textContent = `${current} / ${goal}`;
  if (badCodesDots) {
    const dots = [];
    for (let i = 0; i < goal; i += 1) {
      const lit = i < current ? "lit" : "";
      dots.push(`<span class="strike-dot ${lit}"></span>`);
    }
    badCodesDots.innerHTML = dots.join("");
  }
  badCodesPill.classList.toggle("ready", current > 0 && current >= goal - 1);
}

function renderPunishmentsMeter(snap) {
  if (!punishmentsPill) return;
  if (!snap) {
    if (punishmentsCount) punishmentsCount.textContent = "0 / 3";
    punishmentsPill.classList.remove("ready");
    if (lastPunishmentEl) {
      lastPunishmentEl.hidden = true;
      lastPunishmentEl.textContent = "";
    }
    return;
  }
  const limit = Math.max(1, Number(snap.punishments_limit) || 3);
  const current = Math.max(0, Math.min(limit, Number(snap && snap.punishments_received) || 0));
  if (punishmentsCount) punishmentsCount.textContent = `${current} / ${limit}`;
  punishmentsPill.classList.toggle("ready", current > 0 && current >= limit - 1);

  if (lastPunishmentEl) {
    const last = snap && snap.last_punishment ? String(snap.last_punishment) : "";
    if (last) {
      lastPunishmentEl.hidden = false;
      lastPunishmentEl.textContent = `Last punishment: ${last}`;
    } else {
      lastPunishmentEl.hidden = true;
      lastPunishmentEl.textContent = "";
    }
  }
}

function renderClueMinigameMeter(snap) {
  if (!clueMinigamePill) return;
  const goal = Math.max(1, Number(snap && snap.good_rfid_goal) || 3);
  const progress = Math.max(0, Math.min(goal, Number(snap && snap.good_rfid_progress) || 0));
  if (clueCount) clueCount.textContent = `${progress} / ${goal}`;
  if (clueDots) {
    const dots = [];
    for (let i = 0; i < goal; i += 1) {
      const lit = i < progress ? "lit clue-dot-lit" : "";
      dots.push(`<span class="strike-dot ${lit}"></span>`);
    }
    clueDots.innerHTML = dots.join("");
  }
  clueMinigamePill.classList.toggle("ready", progress >= goal - 1 && goal > 0);
}

function setActiveView(snap) {
  const active = !!(snap && snap.locks);
  if (overviewView) overviewView.hidden = active;
  if (activeView) activeView.hidden = !active;
  if (window.NavSetGameActive) window.NavSetGameActive(active);
  if (!active) {
    if (locksEl) locksEl.innerHTML = "";
    if (wonBadge) wonBadge.hidden = true;
    if (gmWonBadge) gmWonBadge.hidden = true;
    if (rfidNextBadEl) {
      rfidNextBadEl.hidden = true;
      rfidNextBadEl.textContent = "";
    }
    renderBadCodesMeter(null);
    renderPunishmentsMeter(null);
    renderClueMinigameMeter(null);
    scheduleLockPreview();
    return;
  }
  renderBadCodesMeter(snap);
  renderPunishmentsMeter(snap);
  renderClueMinigameMeter(snap);
  if (activeDifficulty) {
    const d = (snap.difficulty || "medium").toString();
    const title = d[0].toUpperCase() + d.slice(1);
    activeDifficulty.textContent = `— ${title}`;
  }
  if (rfidNextBadEl) {
    const pct = snap.rfid_bad_chance_percent != null ? snap.rfid_bad_chance_percent : null;
    if (pct != null && !snap.game_over) {
      rfidNextBadEl.hidden = false;
      rfidNextBadEl.textContent = `Next badge scan: ${pct}% bad (rises after each good scan).`;
    } else {
      rfidNextBadEl.hidden = true;
      rfidNextBadEl.textContent = "";
    }
  }
  if (wonBadge) {
    const escaped = snap.won === true || snap.won === "true";
    wonBadge.hidden = !escaped;
  }
  if (gmWonBadge) {
    const gmWon = snap.gm_won === true || snap.gm_won === "true";
    gmWonBadge.hidden = !gmWon;
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

for (const input of Object.values(lockInputs)) {
  if (!input) continue;
  input.addEventListener("input", scheduleLockPreview);
  input.addEventListener("change", scheduleLockPreview);
}
if (btnPlay) {
  btnPlay.addEventListener("click", async () => {
    const locks = selectedLockCounts();
    if (locks.digit3 + locks.letter5 + locks.digit4 < 1) {
      setBanner("Pick at least one lock to start.", "bad");
      return;
    }
    btnPlay.disabled = true;
    try {
      const data = await postJson("/api/game/start", {
        difficulty: selectedDifficulty(),
        digit3: locks.digit3,
        letter5: locks.letter5,
        digit4: locks.digit4,
        punishment_limit: selectedPunishmentLimit(),
      });
      setBanner("Game started.", "ok");
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
      if (msg.snapshot && (msg.snapshot.gm_won === true || msg.snapshot.gm_won === "true")) {
        setBanner("The Gamemaster wins — you failed to escape!", "bad");
      } else {
        setBanner(msg.result.message, bannerToneForResult(msg.result));
      }
    }
    return;
  }
  if (msg.type === "game_stopped") {
    setActiveView(null);
    setBanner("Game ended.", "");
    return;
  }
  if (msg.type === "forced_minigame" && msg.url) {
    if (msg.gm_won) {
      setBanner(msg.game_over_message || "The Gamemaster wins — you failed to escape!", "bad");
      return;
    }
    const scheduled = msg.reason === "three_clues" || msg.reason === "good_scan_bonus";
    const tone = scheduled ? "ok" : "bad";
    const text =
      msg.message ||
      (scheduled
        ? "Three good RFID codes — time for a minigame."
        : "The Gamemaster locks the room — your penance is a minigame.");
    setBanner(text, tone);
    window.setTimeout(() => {
      window.location.href = msg.url;
    }, 1200);
    return;
  }
  if (msg.type === "punishment_text") {
    const text = msg.gm_won
      ? msg.game_over_message || "The Gamemaster wins — you failed to escape!"
      : "Punishment: " + (msg.message || "The Gamemaster claims this one.");
    setBanner(text, "bad");
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
  await loadSetup();
  try {
    const res = await fetch("/api/game/status");
    const data = await res.json();
    setActiveView(data.snapshot);
  } catch {
    /* offline */
  }
  connectWs();
})();
