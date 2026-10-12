const banner = document.getElementById("banner");
const setupError = document.getElementById("setup-error");
const locksEl = document.getElementById("locks");
const btnPlay = document.getElementById("btn-play");
const overviewView = document.getElementById("overview-view");
const readyView = document.getElementById("ready-view");
const btnBegin = document.getElementById("btn-begin");
const btnReadyCancel = document.getElementById("btn-ready-cancel");
const btnFinaleAgain = document.getElementById("btn-finale-again");
const activeView = document.getElementById("active-view");
const wonBadge = document.getElementById("won-badge");
const badCodesPill = document.getElementById("bad-codes-pill");
const badCodesDots = document.getElementById("bad-codes-dots");
const badCodesCount = document.getElementById("bad-codes-count");
const punishmentsPill = document.getElementById("punishments-pill");
const punishmentsCount = document.getElementById("punishments-count");
const gmWonBadge = document.getElementById("gm-won-badge");
const setupModal = document.getElementById("setup-modal");
const btnSetupCancel = document.getElementById("btn-setup-cancel");
const btnSetupReroll = document.getElementById("btn-setup-reroll");
const btnSetupStart = document.getElementById("btn-setup-start");
const gmControls = document.getElementById("gm-controls");
const gmStatusLine = document.getElementById("gm-status-line");
const wheelModal = document.getElementById("wheel-modal");
const wheelSpinStage = document.getElementById("wheel-spin-stage");
const wheelResultStage = document.getElementById("wheel-result-stage");
const wheelSpinner = document.getElementById("wheel-spinner");
const wheelPunishmentLabel = document.getElementById("wheel-punishment-label");
const wheelPunishmentText = document.getElementById("wheel-punishment-text");
const wheelCountdownWrap = document.querySelector(".wheel-countdown");
const wheelCountdownNum = document.getElementById("wheel-countdown-num");
const wheelCountdownHint = document.getElementById("wheel-countdown-hint");
const wheelResultKicker = document.getElementById("wheel-result-kicker");

const LOCK_KINDS = ["lock4", "digit4"];
const lockInputs = {
  lock4: document.getElementById("lock-lock4"),
  digit4: document.getElementById("lock-digit4"),
};
const lockStepButtons = {};
document.querySelectorAll('button[data-lock-kind][data-delta]').forEach((btn) => {
  const kind = btn.dataset.lockKind;
  const delta = Number(btn.dataset.delta);
  if (!kind || !Number.isFinite(delta)) return;
  if (!lockStepButtons[kind]) lockStepButtons[kind] = {};
  lockStepButtons[kind][delta] = btn;
});
const gmPreviewEl = document.getElementById("gm-preview");

let previewTimer = null;

const WHEEL_SPIN_MS = 4000;
let wheelModalOpen = false;
let wheelModalMode = null;
let wheelSpinTimer = null;
let punishmentTimerEndsAtMs = null;
let punishmentTimerTick = null;
let punishmentTimerKind = null;

function normalizeWheelPunishment(punishment) {
  const p = punishment || {};
  let label = (p.label != null ? String(p.label) : "").trim();
  let message = (p.message != null ? String(p.message) : "").trim();
  if (!label && message) {
    label = message;
    message = "";
  }
  if (message && message === label) message = "";
  return { label, message };
}

function applyWheelPunishmentDisplay(labelEl, textEl, punishment, { fallbackLabel = "Punishment" } = {}) {
  const { label, message } = normalizeWheelPunishment(punishment);
  const heading = label || message || fallbackLabel;
  if (labelEl) {
    labelEl.textContent = heading;
    labelEl.hidden = !heading;
  }
  if (textEl) {
    textEl.textContent = message;
    textEl.hidden = !message;
  }
}

const sfx = window.RoomSounds || null;
const fx = window.RoomFx || null;
const finale = window.RoomFinale || null;

function hideWheelModal() {
  wheelModalOpen = false;
  wheelModalMode = null;
  if (wheelModal) wheelModal.hidden = true;
  if (fx) fx.setAlarm(false);
  if (wheelCountdownHint) wheelCountdownHint.hidden = true;
  if (wheelSpinTimer) {
    window.clearTimeout(wheelSpinTimer);
    wheelSpinTimer = null;
  }
  stopPunishmentTimerTick();
}

function stopPunishmentTimerTick() {
  if (punishmentTimerTick) window.clearInterval(punishmentTimerTick);
  punishmentTimerTick = null;
  punishmentTimerEndsAtMs = null;
  punishmentTimerKind = null;
  if (wheelCountdownWrap) wheelCountdownWrap.hidden = true;
  if (wheelCountdownHint) wheelCountdownHint.hidden = true;
}

function renderPunishmentWheelCountdown() {
  if (!wheelModalOpen || punishmentTimerEndsAtMs == null) return;
  if (wheelCountdownWrap) wheelCountdownWrap.hidden = false;
  const sec = Math.max(0, Math.floor((punishmentTimerEndsAtMs - Date.now()) / 1000));
  if (wheelCountdownNum) {
    wheelCountdownNum.textContent = String(sec);
    wheelCountdownNum.classList.toggle("urgent", sec <= 10);
  }
  if (wheelCountdownHint) {
    wheelCountdownHint.hidden = false;
    if (punishmentTimerKind === "complete") {
      wheelCountdownHint.textContent = "Complete your punishment before time runs out!";
    } else {
      wheelCountdownHint.textContent = "Scan the reward badge before time runs out!";
    }
  }
  if (wheelResultKicker) {
    wheelResultKicker.textContent =
      punishmentTimerKind === "complete" ? "Do your penance" : "Skip window";
  }
}

function syncPunishmentTimerFromSnapshot(snap) {
  if (!wheelModalOpen || !snap) {
    if (!wheelModalOpen) stopPunishmentTimerTick();
    return;
  }
  const resolution = snap.punishment_resolution;
  if (!resolution || resolution === "none") {
    stopPunishmentTimerTick();
    return;
  }
  const remaining = Number(snap.punishment_timer_seconds_remaining);
  const kind = snap.punishment_timer_kind || null;
  if (!Number.isFinite(remaining) || !kind || remaining <= 0) {
    stopPunishmentTimerTick();
    if (wheelResultKicker) wheelResultKicker.textContent = "Punishment";
    return;
  }
  if (kind !== punishmentTimerKind || punishmentTimerEndsAtMs == null) {
    punishmentTimerKind = kind;
    punishmentTimerEndsAtMs = Date.now() + remaining * 1000;
  }
  if (!punishmentTimerTick) {
    punishmentTimerTick = window.setInterval(renderPunishmentWheelCountdown, 1000);
  }
  renderPunishmentWheelCountdown();
}

function showLuckTestModal(snap) {
  if (!wheelModal) return;
  wheelModalOpen = true;
  wheelModalMode = "luck";
  wheelModal.hidden = false;
  if (wheelSpinTimer) {
    window.clearTimeout(wheelSpinTimer);
    wheelSpinTimer = null;
  }
  stopPunishmentTimerTick();
  if (wheelSpinStage) wheelSpinStage.hidden = true;
  if (wheelResultStage) wheelResultStage.hidden = false;
  if (wheelResultKicker) wheelResultKicker.textContent = "Test your luck";
  applyWheelPunishmentDisplay(wheelPunishmentLabel, wheelPunishmentText, {
    label: "Draw a scratch-off card!",
    message: `Pull a ticket from ${gmName(snap)}'s bag and scratch it off.`,
  });
  if (wheelCountdownHint) wheelCountdownHint.hidden = true;
}

function showWheelModal(msg) {
  if (!wheelModal) return;
  wheelModalOpen = true;
  wheelModalMode = "punishment";
  wheelModal.hidden = false;
  if (fx) fx.setAlarm(true);
  if (sfx) sfx.alarm(3);
  if (wheelCountdownHint) wheelCountdownHint.hidden = true;
  if (wheelSpinStage) wheelSpinStage.hidden = false;
  if (wheelResultStage) wheelResultStage.hidden = true;
  if (wheelCountdownWrap) wheelCountdownWrap.hidden = true;
  if (wheelResultKicker) wheelResultKicker.textContent = "Punishment";
  if (wheelSpinTimer) {
    window.clearTimeout(wheelSpinTimer);
    wheelSpinTimer = null;
  }
  if (msg.physical) {
    if (wheelSpinStage) wheelSpinStage.hidden = true;
    if (wheelResultStage) wheelResultStage.hidden = false;
    applyWheelPunishmentDisplay(wheelPunishmentLabel, wheelPunishmentText, msg.punishment);
    if (msg.snapshot) syncPunishmentTimerFromSnapshot(msg.snapshot);
    return;
  }
  if (wheelSpinner) {
    wheelSpinner.classList.remove("spinning");
    void wheelSpinner.offsetWidth;
    wheelSpinner.classList.add("spinning");
  }
  if (msg.snapshot) syncPunishmentTimerFromSnapshot(msg.snapshot);
  wheelSpinTimer = window.setTimeout(() => {
    wheelSpinTimer = null;
    if (wheelSpinStage) wheelSpinStage.hidden = true;
    if (wheelResultStage) wheelResultStage.hidden = false;
    applyWheelPunishmentDisplay(wheelPunishmentLabel, wheelPunishmentText, msg.punishment);
    if (msg.snapshot) syncPunishmentTimerFromSnapshot(msg.snapshot);
  }, WHEEL_SPIN_MS);
}

function syncWheelModalFromSnapshot(snap) {
  if (!snap || snap.punishment_resolution === "none" || !snap.punishment_resolution) {
    if (wheelModalOpen) hideWheelModal();
    return;
  }
  if (snap.punishment_resolution === "luck_test") {
    if (wheelModalMode !== "luck") showLuckTestModal(snap);
    return;
  }
  // Losing ticket: keep the scratch-off card up until the punishment_wheel event spins.
  if (wheelModalMode === "luck") return;
  if (!wheelModalOpen) {
    wheelModalOpen = true;
    wheelModalMode = "punishment";
    if (wheelModal) wheelModal.hidden = false;
    if (fx) fx.setAlarm(true);
    if (wheelSpinStage) wheelSpinStage.hidden = true;
    if (wheelResultStage) wheelResultStage.hidden = false;
    applyWheelPunishmentDisplay(wheelPunishmentLabel, wheelPunishmentText, {
      label: snap.pending_punishment_label,
      message: snap.pending_punishment_message,
    });
  }
  syncPunishmentTimerFromSnapshot(snap);
}

function gmName(snap) {
  return (snap && snap.gamemaster_name) || "Gamemaster";
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
  if (!gmPreviewEl || !setupModal || setupModal.hidden) return;
  const locks = selectedLockCounts();
  if (totalLocks(locks) < 1) {
    renderGmPreview([]);
    return;
  }
  renderGmPreview([], { loading: true });
  try {
    const data = await postJson("/api/game/preview", locks);
    renderGmPreview(data.programming || []);
  } catch (e) {
    renderGmPreview([], { error: String(e.message || e) });
  }
}

function selectedLockCounts() {
  const counts = {};
  for (const kind of LOCK_KINDS) {
    counts[kind] = Math.max(0, parseInt(lockInputs[kind]?.value || "0", 10) || 0);
  }
  return counts;
}

function totalLocks(counts) {
  return LOCK_KINDS.reduce((sum, kind) => sum + counts[kind], 0);
}

function syncStepButtons() {
  for (const kind of LOCK_KINDS) {
    const minus = lockStepButtons[kind]?.[-1];
    if (minus) minus.disabled = (parseInt(lockInputs[kind]?.value || "0", 10) || 0) <= 0;
  }
}

function openSetupModal() {
  if (!setupModal) return;
  setSetupError("");
  setupModal.hidden = false;
  syncStepButtons();
  refreshLockPreview();
}

function closeSetupModal() {
  if (previewTimer) window.clearTimeout(previewTimer);
  previewTimer = null;
  if (setupModal) setupModal.hidden = true;
}

function kindLabel(kind) {
  if (kind === "lock4") return "Lock";
  if (kind === "digit4") return "Lockbox";
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
  if (lock.solved) return "UNLOCKED";
  if (lock.fully_revealed) return "CODE RECOVERED";
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
      dots.push(`<span class="strike-dot ${i < current ? "lit" : ""}"></span>`);
    }
    badCodesDots.innerHTML = dots.join("");
  }
  badCodesPill.classList.toggle("ready", current > 0 && current >= goal - 1);
}

function renderPunishmentsMeter(snap) {
  if (!punishmentsPill) return;
  const show = !!snap;
  punishmentsPill.hidden = !show;
  if (!show) return;
  const limit = Number(snap.punishments_limit);
  const capped = Number.isFinite(limit) && limit > 0;
  const current = Math.max(0, Number(snap.punishments_received) || 0);
  if (punishmentsCount) {
    punishmentsCount.textContent = capped ? `${current} / ${limit}` : String(current);
  }
  punishmentsPill.title = capped
    ? "Each time the punishment wheel spins. If this reaches the limit, the Gamemaster wins."
    : "Wheel punishments received this game.";
  punishmentsPill.classList.toggle("ready", capped && current > 0 && current >= limit - 1);
}

function renderGmControls(snap) {
  if (!gmControls) return;
  if (!snap || snap.game_over) {
    gmControls.hidden = true;
    if (gmStatusLine) gmStatusLine.textContent = "";
    return;
  }
  const parts = [];
  if (snap.punishment_resolution === "luck_test") {
    parts.push("Scratch-off pending — reward badge if it wins, punishment card if it loses.");
  }
  if (snap.punishment_resolution === "trump_window") {
    parts.push("Punishment pending — reward badge to skip, or Gamemaster badge to complete.");
  }
  const rewardCd = Math.max(0, Number(snap.wildcard_free_good_cooldown_seconds) || 0);
  if (rewardCd > 0) {
    parts.push(`Reward badge cooldown: ${rewardCd}s.`);
  }
  gmControls.hidden = parts.length === 0;
  if (gmStatusLine) gmStatusLine.textContent = parts.join(" ");
}

function setActiveView(snap) {
  const ready = !!snap && snap.phase === "ready";
  const active = !!snap && !ready;
  if (overviewView) overviewView.hidden = !!snap;
  if (readyView) readyView.hidden = !ready;
  if (activeView) activeView.hidden = !active;
  if (window.NavSetGameActive) window.NavSetGameActive(!!snap);
  if (ready) closeSetupModal();
  if (!active) {
    if (finale) finale.close();
    if (locksEl) locksEl.innerHTML = "";
    if (wonBadge) wonBadge.hidden = true;
    if (gmWonBadge) gmWonBadge.hidden = true;
    renderBadCodesMeter(null);
    renderPunishmentsMeter(null);
    renderGmControls(null);
    hideWheelModal();
    return;
  }
  closeSetupModal();

  renderBadCodesMeter(snap);
  renderPunishmentsMeter(snap);
  renderGmControls(snap);
  syncWheelModalFromSnapshot(snap);

  const escaped = snap.won === true || snap.won === "true";
  if (wonBadge) wonBadge.hidden = !escaped;
  if (escaped && finale) finale.show(snap);
  if (gmWonBadge) {
    const gmWon = snap.gm_won === true || snap.gm_won === "true";
    gmWonBadge.hidden = !gmWon;
  }
  if (locksEl) {
    locksEl.innerHTML = "";
    const locks = snap.locks || [];
    locks.forEach((lock) => {
      const card = document.createElement("div");
      const classes = ["lock-card"];
      if (lock.solved) classes.push("solved");
      else if (lock.fully_revealed) classes.push(lock.kind === "digit4" ? "revealed" : "solved");
      card.className = classes.join(" ");
      card.innerHTML = `
        <div class="lock-kind">${kindLabel(lock.kind)}</div>
        <div class="lock-state">${lockStateLabel(lock)}</div>
        <div class="lock-clues">${formatClues(lock)}</div>
      `;
      locksEl.appendChild(card);
    });
  }
}

function setSetupError(text) {
  if (!setupError) return;
  if (text) {
    setupError.textContent = text;
    setupError.hidden = false;
  } else {
    setupError.textContent = "";
    setupError.hidden = true;
  }
}

function setBanner(text, tone) {
  if (!banner) return;
  banner.textContent = text || "";
  banner.classList.remove("ok", "bad");
  if (tone === "ok") banner.classList.add("ok");
  if (tone === "bad") banner.classList.add("bad");
  if (text && overviewView && !overviewView.hidden) {
    banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function bannerToneForResult(r) {
  const inter = r.interaction || "lock";
  if (inter === "rfid_exhausted") return "";
  if (inter === "rfid_good") return "ok";
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

for (const [kind, buttonsByDelta] of Object.entries(lockStepButtons)) {
  const input = lockInputs[kind];
  if (!input) continue;
  for (const [deltaStr, btn] of Object.entries(buttonsByDelta)) {
    const delta = Number(deltaStr);
    if (!btn || !Number.isFinite(delta)) continue;
    btn.addEventListener("click", () => {
      const current = parseInt(input.value || "0", 10) || 0;
      input.value = String(Math.max(0, current + delta));
      syncStepButtons();
      scheduleLockPreview();
      setSetupError("");
    });
  }
}

if (btnPlay) btnPlay.addEventListener("click", openSetupModal);
if (btnSetupCancel) btnSetupCancel.addEventListener("click", closeSetupModal);
if (btnSetupReroll) btnSetupReroll.addEventListener("click", refreshLockPreview);

if (btnSetupStart) {
  btnSetupStart.addEventListener("click", async () => {
    const locks = selectedLockCounts();
    if (totalLocks(locks) < 1) {
      setSetupError("Pick at least one lock to start the game.");
      return;
    }
    setSetupError("");
    btnSetupStart.disabled = true;
    try {
      const data = await postJson("/api/game/start", locks);
      closeSetupModal();
      setBanner("");
      setActiveView(data.snapshot);
    } catch (e) {
      setSetupError(String(e.message || e));
    } finally {
      btnSetupStart.disabled = false;
    }
  });
}

if (btnBegin) {
  btnBegin.addEventListener("click", async () => {
    btnBegin.disabled = true;
    try {
      const data = await postJson("/api/game/begin", {});
      setBanner("Let the game begin.", "ok");
      setActiveView(data.snapshot);
      playIntro(data.snapshot);
    } catch (e) {
      setBanner(String(e.message || e), "bad");
    } finally {
      btnBegin.disabled = false;
    }
  });
}

async function stopGame() {
  try {
    await postJson("/api/game/stop", {});
  } catch (e) {
    setBanner(String(e.message || e), "bad");
    return;
  }
  setActiveView(null);
  setBanner("");
}

if (btnReadyCancel) btnReadyCancel.addEventListener("click", stopGame);
if (btnFinaleAgain) btnFinaleAgain.addEventListener("click", stopGame);

function playIntro(snap) {
  if (!fx || !snap) return;
  fx.intro.show({ key: snap.started_at_iso });
}

if (fx) {
  fx.intro.onClosed(() => {
    postJson("/api/game/intro-done", {}).catch(() => {});
  });
}

const BROKEN_CLUE_INTERACTIONS = new Set(["rfid_punishment", "lock", "luck_failure"]);

function playResultCue(result, snap) {
  if (!sfx && !fx) return;
  if (snap && (snap.gm_won === true || snap.gm_won === "true")) {
    if (sfx) sfx.powerDown();
    if (fx) fx.glitch();
    return;
  }
  // Wins get the finale's fanfare instead.
  if (result.won) return;
  const tone = bannerToneForResult(result);
  if (tone === "ok") {
    if (sfx) sfx.chirp();
  } else if (tone === "bad") {
    if (BROKEN_CLUE_INTERACTIONS.has(result.interaction || "lock")) {
      if (sfx) sfx.glitch();
      if (fx) fx.glitch();
    } else if (sfx) {
      sfx.buzz();
    }
  }
}

function applyWsMessage(msg) {
  if (msg.type === "game_started") {
    setBanner("Let the game begin.", "ok");
    playIntro(msg.snapshot);
  }
  if (msg.type === "intro_continue") {
    if (fx) fx.intro.continueIfFinished();
    return;
  }
  if (msg.type === "intro_done") {
    if (fx) fx.intro.close();
    return;
  }
  if (msg.type === "hello") {
    hideWheelModal();
    setActiveView(msg.snapshot);
    return;
  }
  if (
    msg.type === "game_armed" ||
    msg.type === "game_started" ||
    msg.type === "code_result" ||
    msg.type === "luck_test" ||
    msg.type === "luck_test_passed" ||
    msg.type === "trump_used" ||
    msg.type === "punishment_wheel" ||
    msg.type === "punishment_resolved"
  ) {
    if (msg.snapshot) setActiveView(msg.snapshot);
    if (msg.type === "punishment_wheel") {
      showWheelModal(msg);
      setBanner(
        msg.physical ? "Punishment time — spin the wheel and roll the dice!" : "The wheel of punishments has spoken!",
        "bad"
      );
      return;
    }
    if (msg.type === "code_result" && msg.result) {
      playResultCue(msg.result, msg.snapshot);
      if (msg.snapshot && (msg.snapshot.gm_won === true || msg.snapshot.gm_won === "true")) {
        setBanner(
          `${gmName(msg.snapshot)} wins — the prisoner stays bound.`,
          "bad"
        );
      } else if (msg.result.won) {
        setBanner(msg.result.message, "ok");
      } else {
        setBanner(msg.result.message, bannerToneForResult(msg.result));
      }
    }
    if (msg.type === "luck_test") {
      if (sfx) sfx.alarm(2);
      if (fx) fx.glitch();
      setBanner(msg.message || "Three broken clues — draw a scratch-off card!", "bad");
    }
    if (msg.type === "luck_test_passed") {
      hideWheelModal();
      if (sfx) sfx.chirp();
      setBanner(msg.message || "Winning ticket — no punishment this time!", "ok");
    }
    if (msg.type === "trump_used") {
      hideWheelModal();
      setBanner(msg.message || "Reward badge — punishment skipped!", "ok");
      return;
    }
    return;
  }
  if (msg.type === "game_stopped") {
    hideWheelModal();
    if (fx) fx.intro.close();
    setActiveView(null);
    setBanner("Game ended.", "");
    return;
  }
  if (msg.type === "punishment_text") {
    if (msg.reason === "punishment_wheel") hideWheelModal();
    if (msg.snapshot) setActiveView(msg.snapshot);
    let text;
    if (msg.gm_won && sfx) sfx.powerDown();
    if (msg.gm_won) text = msg.game_over_message || "The Gamemaster wins!";
    else if (msg.physical) text = msg.message || "Punishment dealt.";
    else text = "Punishment: " + (msg.message || "The Gamemaster claims this one.");
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
  try {
    const res = await fetch("/api/game/status");
    const data = await res.json();
    setActiveView(data.snapshot);
  } catch {
    /* offline */
  }
  connectWs();
})();
