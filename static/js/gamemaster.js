const modeEl = document.getElementById("gmc-mode");
const stateEl = document.getElementById("gmc-state");
const messageEl = document.getElementById("gmc-message");
const statsEl = document.getElementById("gmc-stats");
const logEl = document.getElementById("gmc-log");
const actionButtons = Array.from(document.querySelectorAll(".gm-console-btn[data-outcome]"));
const badgeButtons = Array.from(document.querySelectorAll(".gm-console-badge[data-badge]"));

let currentSnap = null;
let busy = false;
let lastMessage = null;

function isTrue(v) {
  return v === true || v === "true";
}

function pendingText(snap) {
  if (!snap || !snap.punishment_resolution || snap.punishment_resolution === "none") return "";
  if (snap.punishment_resolution === "luck_test") {
    return "Scratch-off pending — scan the reward badge if the ticket wins, or the punishment card if it loses.";
  }
  const label = snap.pending_punishment_label || "Punishment";
  const msg = snap.pending_punishment_message && snap.pending_punishment_message !== label
    ? ` — ${snap.pending_punishment_message}`
    : "";
  return `Pending: ${label}${msg} — skip it with the reward badge or complete it with the Gamemaster badge.`;
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
  if (inter === "rfid_good") return "ok";
  return r.ok ? "ok" : "bad";
}

function stateFor(snap) {
  if (!snap) return { label: "Idle", cls: "idle" };
  if (snap.phase === "ready") return { label: "Waiting to start", cls: "warn" };
  if (isTrue(snap.intro_active)) return { label: "Intro playing", cls: "warn" };
  if (isTrue(snap.gm_won)) return { label: `${snap.gamemaster_name || "Gamemaster"} wins`, cls: "bad" };
  if (isTrue(snap.won)) return { label: "Prisoner freed", cls: "ok" };
  if (snap.punishment_resolution === "luck_test") return { label: "Scratch-off pending", cls: "warn" };
  if (snap.punishment_resolution && snap.punishment_resolution !== "none") {
    return { label: "Punishment pending", cls: "bad" };
  }
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
  if (snap.phase === "ready") {
    statsEl.innerHTML =
      '<p class="muted">Room armed. Finish setting up, then scan your reward badge (or press Start game below) to play the intro.</p>';
    return;
  }
  const items = [];
  const badGoal = Math.max(1, Number(snap.bad_codes_goal) || 3);
  const badNow = Math.max(0, Number(snap.bad_codes_progress) || 0);
  items.push(stat("Broken clues", `${badNow} / ${badGoal}`, badNow >= badGoal - 1 && badNow > 0 ? "bad" : ""));

  const limit = Number(snap.punishments_limit) || 0;
  const received = Math.max(0, Number(snap.punishments_received) || 0);
  items.push(stat("Punishments", limit > 0 ? `${received} / ${limit}` : String(received)));

  if (snap.rfid_bad_chance_percent != null && !isTrue(snap.game_over)) {
    items.push(stat("Next scan bad", `${snap.rfid_bad_chance_percent}%`));
  }

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
  const lockboxes = locks.filter((l) => l.kind === "digit4");
  if (lockboxes.length) {
    const open = lockboxes.filter((l) => l.solved).length;
    items.push(stat("Lockboxes open", `${open} / ${lockboxes.length}`, open === lockboxes.length ? "ok" : ""));
  }
  statsEl.innerHTML = items.join("");
}

/** variant: "luck" | "ready" | "intro" | "skip" | null — swaps in the button's data-<variant>-title / -sub labels. */
function syncBadgeLabel(btn, variant) {
  const titleEl = btn.querySelector(".gm-console-badge-title");
  const subEl = btn.querySelector(".gm-console-badge-sub");
  if (titleEl && btn.dataset.defaultTitle === undefined) btn.dataset.defaultTitle = titleEl.textContent;
  if (subEl && btn.dataset.defaultSub === undefined) btn.dataset.defaultSub = subEl.textContent;
  const title = variant && btn.dataset[`${variant}Title`];
  const sub = variant && btn.dataset[`${variant}Sub`];
  if (titleEl) titleEl.textContent = title || btn.dataset.defaultTitle;
  if (subEl) subEl.textContent = sub || btn.dataset.defaultSub;
}

function hasOpenableLockbox(snap) {
  if (!snap) return false;
  const locks = snap.locks || [];
  const lockboxes = locks.filter((l) => l.kind === "digit4");
  return (lockboxes.length ? lockboxes : locks).some(
    (l) => !l.solved && (l.clues || []).some((c) => c != null && c !== "")
  );
}

function syncButtons() {
  const snap = currentSnap;
  const resolution = (snap && snap.punishment_resolution) || "none";
  const pending = resolution !== "none";
  const luck = resolution === "luck_test";
  const ready = !!snap && snap.phase === "ready";
  const intro = !!snap && isTrue(snap.intro_active);
  const usable = !!snap && !isTrue(snap.game_over) && !pending && !ready;
  for (const btn of actionButtons) btn.disabled = busy || !usable;
  for (const btn of badgeButtons) {
    let ok;
    if (btn.dataset.badge === "reward") ok = usable || ready || pending;
    else if (btn.dataset.badge === "lockbox") ok = usable && hasOpenableLockbox(snap);
    else ok = pending;
    btn.disabled = busy || !ok;
    syncBadgeLabel(btn, ready ? "ready" : intro ? "intro" : luck ? "luck" : pending ? "skip" : null);
  }
}

function render(snap) {
  currentSnap = snap || null;
  const s = currentSnap;
  if (window.NavSetGameActive) window.NavSetGameActive(!!s);
  if (modeEl) modeEl.textContent = s ? "Classic Escape" : "No game running";
  if (stateEl) {
    const { label, cls } = stateFor(s);
    stateEl.textContent = label;
    stateEl.className = `gm-console-state ${cls}`;
  }
  renderMessage();
  renderStats(s);
  syncButtons();
}

function applyWsMessage(msg) {
  if (msg.snapshot !== undefined && msg.type !== "punishment_text") render(msg.snapshot);
  switch (msg.type) {
    case "game_armed":
      addLog("Room armed — scan the reward badge to start the game.", "ok");
      break;
    case "game_started":
      addLog("Game started — scan the reward or Gamemaster badge once the intro finishes.", "ok");
      break;
    case "intro_done":
      addLog("Intro closed.", "ok");
      break;
    case "game_stopped":
      render(null);
      addLog("Game ended.", "");
      break;
    case "code_result":
      if (msg.result) addLog(msg.result.message, toneForResult(msg.result));
      break;
    case "luck_test":
      addLog("Scratch-off time — scan the reward badge if the ticket wins, or the punishment card if it loses.", "bad");
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
    case "trump_used":
      addLog(msg.message || "Reward badge — punishment skipped.", "ok");
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
