const modeEl = document.getElementById("gmc-mode");
const difficultyEl = document.getElementById("gmc-difficulty");
const stateEl = document.getElementById("gmc-state");
const timerEl = document.getElementById("gmc-timer");
const messageEl = document.getElementById("gmc-message");
const statsEl = document.getElementById("gmc-stats");
const logEl = document.getElementById("gmc-log");
const actionButtons = Array.from(document.querySelectorAll(".gm-console-btn[data-outcome]"));
const badgeButtons = Array.from(document.querySelectorAll(".gm-console-badge[data-badge]"));

const MODE_LABELS = {
  breakout: "Breakout",
  deadline: "Deadline",
  bounty: "Bounty",
};
let currentSnap = null;
let busy = false;
let timerEndsAtMs = null;
let timerTick = null;
let lastMessage = null;

function isTrue(v) {
  return v === true || v === "true";
}

function formatTimer(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function pendingText(snap) {
  if (!snap || !snap.punishment_resolution || snap.punishment_resolution === "none") return "";
  const label = snap.pending_punishment_label || "Punishment";
  const msg = snap.pending_punishment_message && snap.pending_punishment_message !== label
    ? ` — ${snap.pending_punishment_message}`
    : "";
  return `Pending: ${label}${msg} — skip or complete it below, or scan a badge.`;
}

function renderMessage() {
  if (!messageEl) return;
  const fallback = pendingText(currentSnap);
  const text = lastMessage?.text || fallback;
  const tone = lastMessage?.text ? lastMessage.tone : fallback ? "bad" : "";
  messageEl.hidden = !text;
  messageEl.textContent = text;
  messageEl.classList.remove("ok", "bad");
  if (tone) messageEl.classList.add(tone);
}

function showMessage(text, tone) {
  if (!text) return;
  lastMessage = { text, tone: tone || "" };
  renderMessage();
}

function addLog(text, tone) {
  if (!text) return;
  showMessage(text, tone);
  if (!logEl) return;
  const li = document.createElement("li");
  if (tone) li.classList.add(tone);
  const time = document.createElement("span");
  time.className = "gm-console-log-time";
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const msg = document.createElement("span");
  msg.textContent = text;
  li.append(time, msg);
  logEl.prepend(li);
}

function toneForResult(r) {
  const inter = r.interaction || "lock";
  if (inter === "rfid_exhausted") return "";
  if (inter === "rfid_collect" || inter === "rfid_good" || inter === "reward_badge") return "ok";
  return r.ok ? "ok" : "bad";
}

function stateFor(snap) {
  if (!snap) return { label: "Idle", cls: "idle" };
  if (isTrue(snap.gm_won)) return { label: `${snap.gamemaster_name || "Gamemaster"} wins`, cls: "bad" };
  if (isTrue(snap.won)) return { label: snap.game_mode === "breakout" ? "Escaped" : "Players win", cls: "ok" };
  if (snap.punishment_resolution && snap.punishment_resolution !== "none") {
    return { label: "Punishment pending", cls: "bad" };
  }
  if (snap.phase === "punishment") return { label: "Punishment", cls: "bad" };
  if (snap.phase === "collection") return { label: "Collecting RFIDs", cls: "warn" };
  return { label: "Playing", cls: "ok" };
}

function stat(label, value, cls = "") {
  return `<div class="gm-console-stat ${cls}"><span class="gm-console-stat-label">${label}</span><span class="gm-console-stat-value">${value}</span></div>`;
}

function renderStats(snap) {
  if (!statsEl) return;
  if (!snap) {
    statsEl.innerHTML = '<p class="muted">Start a game on the Play screen — this page updates live.</p>';
    return;
  }
  const mode = snap.game_mode;
  const items = [];
  const badGoal = Math.max(1, Number(snap.bad_codes_goal) || 3);
  const badNow = Math.max(0, Number(snap.bad_codes_progress) || 0);
  items.push(stat("Bad codes", `${badNow} / ${badGoal}`, badNow >= badGoal - 1 && badNow > 0 ? "bad" : ""));

  const limit = Number(snap.punishments_limit) || 0;
  const received = Math.max(0, Number(snap.punishments_received) || 0);
  items.push(stat("Punishments", limit > 0 ? `${received} / ${limit}` : String(received)));

  if (snap.rfid_bad_chance_percent != null && snap.phase !== "collection" && !isTrue(snap.game_over)) {
    items.push(stat("Next scan bad", `${snap.rfid_bad_chance_percent}%`));
  }

  if (mode === "breakout") {
    const locks = snap.locks || [];
    const revealed = locks.filter((l) => l.solved || l.fully_revealed).length;
    let shown = 0;
    let total = 0;
    for (const l of locks) {
      for (const c of l.clues || []) {
        total += 1;
        if (c != null && c !== "") shown += 1;
      }
    }
    items.push(stat("Codes revealed", `${revealed} / ${locks.length}`, revealed === locks.length && locks.length ? "ok" : ""));
    items.push(stat("Clues revealed", `${shown} / ${total}`));
  }

  if (mode === "bounty") {
    items.push(stat("Rewards", `${snap.rewards_earned || 0} / ${snap.rewards_to_win || 5}`, "ok"));
    items.push(stat("Good codes", `${snap.good_codes_progress || 0} / ${snap.good_codes_per_reward || 5}`));
  }

  if (snap.phase === "collection" && (mode === "deadline" || mode === "bounty")) {
    items.push(stat("RFIDs scanned", `${snap.rfids_collected || 0} / ${snap.rfids_per_punishment || 4}`));
  }

  if (isTrue(snap.minigames_enabled) && (mode === "breakout" || mode === "bounty")) {
    items.push(stat("Minigame meter", `${snap.good_rfid_progress || 0} / ${snap.good_rfid_goal || 3}`));
  }
  statsEl.innerHTML = items.join("");
}

function stopTimer() {
  if (timerTick) window.clearInterval(timerTick);
  timerTick = null;
  timerEndsAtMs = null;
  if (timerEl) timerEl.hidden = true;
}

function renderTimer() {
  if (!timerEl || timerEndsAtMs == null) return;
  const sec = Math.max(0, Math.floor((timerEndsAtMs - Date.now()) / 1000));
  timerEl.textContent = `Round ${currentSnap?.deadline_cycle || 1} · ${formatTimer(sec)} left`;
  timerEl.classList.toggle("timer-urgent", sec <= 60);
}

function syncTimer(snap) {
  const remaining = Number(snap?.timer_seconds_remaining);
  if (!snap || snap.game_mode !== "deadline" || snap.phase !== "playing" || !Number.isFinite(remaining)) {
    stopTimer();
    return;
  }
  timerEndsAtMs = Date.now() + remaining * 1000;
  if (timerEl) timerEl.hidden = false;
  if (!timerTick) timerTick = window.setInterval(renderTimer, 1000);
  renderTimer();
}

function syncButtons() {
  const snap = currentSnap;
  const pending = !!(snap && snap.punishment_resolution && snap.punishment_resolution !== "none");
  const usable = !!snap && !isTrue(snap.game_over) && !pending;
  for (const btn of actionButtons) btn.disabled = busy || !usable;
  for (const btn of badgeButtons) {
    const ok = btn.dataset.badge === "reward" ? usable : pending;
    btn.disabled = busy || !ok;
  }
}

function render(snap) {
  currentSnap = snap && snap.started_at_iso ? snap : null;
  const s = currentSnap;
  if (window.NavSetGameActive) window.NavSetGameActive(!!s);
  if (modeEl) modeEl.textContent = s ? MODE_LABELS[s.game_mode] || "Game" : "No game running";
  if (difficultyEl) {
    const d = s ? String(s.difficulty || "") : "";
    difficultyEl.textContent = d ? `— ${d[0].toUpperCase()}${d.slice(1)}` : "";
  }
  if (stateEl) {
    const { label, cls } = stateFor(s);
    stateEl.textContent = label;
    stateEl.className = `gm-console-state ${cls}`;
  }
  renderMessage();
  renderStats(s);
  syncTimer(s);
  syncButtons();
}

function applyWsMessage(msg) {
  if (msg.snapshot !== undefined && msg.type !== "punishment_text") render(msg.snapshot);
  switch (msg.type) {
    case "game_started":
      addLog("Game started.", "ok");
      break;
    case "game_stopped":
      render(null);
      addLog("Game ended.", "");
      break;
    case "code_result":
      if (msg.result) addLog(msg.result.message, toneForResult(msg.result));
      break;
    case "punishment_wheel": {
      const p = msg.punishment || {};
      addLog(
        msg.physical
          ? "Punishment triggered — spin the physical wheel, then a player rolls the dice."
          : `Wheel spun: ${p.label || p.message || "Punishment"}`,
        "bad"
      );
      break;
    }
    case "punishment_text":
      if (msg.snapshot) render(msg.snapshot);
      if (msg.gm_won) addLog(msg.game_over_message || "Gamemaster wins.", "bad");
      else addLog(msg.physical ? msg.message : `Punishment: ${msg.message || ""}`, msg.physical ? "ok" : "bad");
      break;
    case "forced_minigame":
      addLog(msg.message || "Minigame launched.", msg.reason === "punishment_wheel" ? "bad" : "ok");
      break;
    case "timer_expired":
      addLog("Timer expired — wheel spins.", "bad");
      break;
    case "timer_restarted":
      addLog("All RFIDs scanned — timer restarted.", "ok");
      break;
    case "bounty_collection_complete":
      addLog("Bounty batch complete.", "ok");
      break;
    case "trump_used":
      addLog(msg.message || "Skip badge used.", "ok");
      break;
    case "punishment_complete":
      addLog("Punishment complete.", "ok");
      break;
    default:
      break;
  }
}

async function gmPost(url, body) {
  busy = true;
  syncButtons();
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || res.statusText);
    if (data.result) showMessage(data.result.message, toneForResult(data.result));
    if (data.snapshot !== undefined) render(data.snapshot);
  } catch (e) {
    showMessage(String(e.message || e), "bad");
  } finally {
    busy = false;
    syncButtons();
  }
}

for (const btn of actionButtons) {
  btn.addEventListener("click", () => gmPost("/api/gm/virtual-scan", { outcome: btn.dataset.outcome }));
}
for (const btn of badgeButtons) {
  btn.addEventListener("click", () => gmPost("/api/gm/virtual-badge", { badge: btn.dataset.badge }));
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
    pingTimer = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 25000);
  });
  ws.addEventListener("close", () => {
    if (pingTimer) window.clearInterval(pingTimer);
    window.setTimeout(connectWs, 1200);
  });
}

render(null);
connectWs();
