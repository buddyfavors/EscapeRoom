const banner = document.getElementById("banner");
const setupError = document.getElementById("setup-error");
const locksEl = document.getElementById("locks");
const locksSection = document.getElementById("locks-section");
const btnPlay = document.getElementById("btn-play");
const overviewView = document.getElementById("overview-view");
const activeView = document.getElementById("active-view");
const phaseBanner = document.getElementById("phase-banner");
const timerDisplay = document.getElementById("timer-display");
const wonBadge = document.getElementById("won-badge");
const bountyWonBadge = document.getElementById("bounty-won-badge");
const badCodesPill = document.getElementById("bad-codes-pill");
const badCodesDots = document.getElementById("bad-codes-dots");
const badCodesCount = document.getElementById("bad-codes-count");
const clueMinigamePill = document.getElementById("clue-minigame-pill");
const clueDots = document.getElementById("clue-dots");
const clueCount = document.getElementById("clue-count");
const punishmentsPill = document.getElementById("punishments-pill");
const punishmentsCount = document.getElementById("punishments-count");
const gmWonBadge = document.getElementById("gm-won-badge");
const rewardsPill = document.getElementById("rewards-pill");
const rewardsCount = document.getElementById("rewards-count");
const bountyGoodPill = document.getElementById("bounty-good-pill");
const bountyGoodCount = document.getElementById("bounty-good-count");
const collectionPill = document.getElementById("collection-pill");
const collectionCount = document.getElementById("collection-count");
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
let timerTick = null;
let timerEndsAtMs = null;
let timerShrinkNote = "";
let timerCycle = 1;

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
      wheelCountdownHint.textContent = "Scan your skip badge before time runs out!";
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

function stopTimerTick() {
  if (timerTick) window.clearInterval(timerTick);
  timerTick = null;
  timerEndsAtMs = null;
}

function formatTimer(sec) {
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function syncTimerFromSnapshot(snap) {
  if (!timerDisplay) return;
  if (!snap || snap.game_mode !== "deadline" || snap.phase !== "playing") {
    timerDisplay.hidden = true;
    stopTimerTick();
    return;
  }
  const remaining = Number(snap.timer_seconds_remaining);
  if (Number.isFinite(remaining)) {
    timerEndsAtMs = Date.now() + remaining * 1000;
  } else if (snap.timer_ends_at_iso) {
    timerEndsAtMs = new Date(snap.timer_ends_at_iso).getTime();
  } else {
    timerDisplay.hidden = true;
    stopTimerTick();
    return;
  }
  timerDisplay.hidden = false;
  timerDisplay.classList.toggle("timer-urgent", remaining <= 60);
  timerCycle = Number(snap.deadline_cycle) || 1;
  timerShrinkNote =
    snap.final_countdown_enabled && timerCycle > (Number(snap.final_countdown_start_after) || 3)
      ? " · Final Countdown active"
      : "";
  if (!timerTick) {
    timerTick = window.setInterval(renderTimerText, 1000);
  }
  renderTimerText();
}

function timerRemainingSec() {
  if (timerEndsAtMs == null) return null;
  return Math.max(0, Math.floor((timerEndsAtMs - Date.now()) / 1000));
}

let lastBeepSec = null;

function renderTimerText() {
  if (!timerDisplay || timerEndsAtMs == null) return;
  const sec = timerRemainingSec();
  timerDisplay.textContent = `Round ${timerCycle} · Time left: ${formatTimer(sec)}${timerShrinkNote}`;
  timerDisplay.classList.toggle("timer-urgent", sec <= 60);
  if (sfx && sec > 0 && sec <= 10 && sec !== lastBeepSec) sfx.countdownBeep(sec <= 3);
  lastBeepSec = sec;
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

function badCodesHint(snap) {
  const effect = snap && snap.bad_code_effect;
  if (effect === "time_penalty") {
    return "Every 3rd broken clue shaves 30 seconds off the clock.";
  }
  if (effect === "lose_progress") {
    return "Every 3rd broken clue steals one step toward your next reward.";
  }
  return "Every 3rd broken clue or wrong lock try means drawing a scratch-off card.";
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
  badCodesPill.title = badCodesHint(snap);
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

function renderClueMinigameMeter(snap) {
  if (!clueMinigamePill) return;
  const mode = snap && snap.game_mode;
  const show = mode === "breakout" || mode === "bounty";
  clueMinigamePill.hidden = !show;
  if (!show) return;
  const goal = Math.max(1, Number(snap.good_rfid_goal) || 3);
  const progress = Math.max(0, Math.min(goal, Number(snap.good_rfid_progress) || 0));
  if (clueCount) clueCount.textContent = `${progress} / ${goal}`;
  if (clueDots) {
    const dots = [];
    for (let i = 0; i < goal; i += 1) {
      dots.push(`<span class="strike-dot ${i < progress ? "lit clue-dot-lit" : ""}"></span>`);
    }
    clueDots.innerHTML = dots.join("");
  }
  clueMinigamePill.classList.toggle("ready", progress >= goal - 1 && goal > 0);
}

function renderBountyMeters(snap) {
  const mode = snap && snap.game_mode;
  const isBounty = mode === "bounty";
  if (rewardsPill) rewardsPill.hidden = !isBounty;
  if (bountyGoodPill) bountyGoodPill.hidden = !isBounty;
  if (!isBounty) {
    if (rewardsCount) rewardsCount.textContent = "";
    if (bountyGoodCount) bountyGoodCount.textContent = "";
    return;
  }
  const toWin = Math.max(1, Number(snap.rewards_to_win) || 5);
  const earned = Math.max(0, Number(snap.rewards_earned) || 0);
  const perReward = Math.max(1, Number(snap.good_codes_per_reward) || 5);
  const progress = Math.max(0, Number(snap.good_codes_progress) || 0);
  if (rewardsCount) rewardsCount.textContent = `${earned} / ${toWin}`;
  if (bountyGoodCount) bountyGoodCount.textContent = `${progress} / ${perReward}`;
}

function renderCollectionMeter(snap) {
  const mode = snap && snap.game_mode;
  const phase = snap && snap.phase;
  const show =
    phase === "collection" && (mode === "deadline" || mode === "bounty");
  if (collectionPill) collectionPill.hidden = !show;
  if (!show) {
    if (collectionCount) collectionCount.textContent = "";
    return;
  }
  const need = Math.max(1, Number(snap.rfids_per_punishment) || 4);
  const got = Math.max(0, Number(snap.rfids_collected) || 0);
  if (collectionCount) collectionCount.textContent = `${got} / ${need}`;
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
    parts.push("Punishment pending — skip badge or Gamemaster complete badge.");
  }
  const rewardCd = Math.max(0, Number(snap.wildcard_free_good_cooldown_seconds) || 0);
  if (rewardCd > 0 && snap.game_mode !== "bounty") {
    parts.push(`Reward badge cooldown: ${rewardCd}s.`);
  }
  gmControls.hidden = parts.length === 0;
  if (gmStatusLine) gmStatusLine.textContent = parts.join(" ");
}

function renderPhaseBanner(snap) {
  if (!phaseBanner) return;
  if (!snap) {
    phaseBanner.hidden = true;
    phaseBanner.textContent = "";
    return;
  }
  const mode = snap.game_mode;
  const phase = snap.phase || "playing";
  if (mode === "deadline") {
    if (phase === "punishment") {
      phaseBanner.hidden = false;
      if (snap.punishment_resolution === "trump_window") {
        phaseBanner.textContent =
          "Wheel landed — complete the punishment, or use skip badge before Gamemaster marks complete.";
      } else {
        phaseBanner.textContent =
          "Finish your punishment, then scan your earned RFIDs.";
      }
    } else if (phase === "collection") {
      phaseBanner.hidden = false;
      phaseBanner.textContent = "Collection phase — scan every RFID the Gamemaster handed out.";
    } else {
      phaseBanner.hidden = true;
      phaseBanner.textContent = "";
    }
    return;
  }
  if (mode === "bounty" && phase === "collection") {
    phaseBanner.hidden = false;
    phaseBanner.textContent =
      "Scan the RFIDs the Gamemaster handed out — good rolls count toward your next reward.";
    return;
  }
  if (mode === "bounty" && phase === "playing" && !snap.game_over) {
    phaseBanner.hidden = false;
    phaseBanner.textContent = "Scan the reward badge to receive your next batch of RFIDs.";
    return;
  }
  phaseBanner.hidden = true;
  phaseBanner.textContent = "";
}

function setActiveView(snap) {
  const active = !!(snap && snap.started_at_iso);
  if (overviewView) overviewView.hidden = active;
  if (activeView) activeView.hidden = !active;
  if (window.NavSetGameActive) window.NavSetGameActive(active);
  if (!active) {
    if (locksEl) locksEl.innerHTML = "";
    if (wonBadge) wonBadge.hidden = true;
    if (bountyWonBadge) bountyWonBadge.hidden = true;
    if (gmWonBadge) gmWonBadge.hidden = true;
    stopTimerTick();
    renderBadCodesMeter(null);
    renderPunishmentsMeter(null);
    renderClueMinigameMeter(null);
    renderBountyMeters(null);
    renderCollectionMeter(null);
    renderPhaseBanner(null);
    renderGmControls(null);
    hideWheelModal();
    return;
  }
  closeSetupModal();

  const mode = snap.game_mode || "breakout";
  if (locksSection) locksSection.hidden = mode !== "breakout";

  renderBadCodesMeter(snap);
  renderPunishmentsMeter(snap);
  renderClueMinigameMeter(snap);
  renderBountyMeters(snap);
  renderCollectionMeter(snap);
  renderPhaseBanner(snap);
  renderGmControls(snap);
  syncWheelModalFromSnapshot(snap);
  syncTimerFromSnapshot(snap);

  if (wonBadge) {
    const escaped = mode === "breakout" && (snap.won === true || snap.won === "true");
    wonBadge.hidden = !escaped;
  }
  if (bountyWonBadge) {
    const won = mode === "bounty" && (snap.won === true || snap.won === "true");
    bountyWonBadge.hidden = !won;
  }
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
  if (inter === "rfid_collect" || inter === "rfid_good" || inter === "reward_badge") return "ok";
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
      setBanner("Let the game begin.", "ok");
      setActiveView(data.snapshot);
      playIntro(data.snapshot);
    } catch (e) {
      setSetupError(String(e.message || e));
    } finally {
      btnSetupStart.disabled = false;
    }
  });
}

function playIntro(snap) {
  if (!fx || !snap) return;
  fx.intro.show({ key: snap.started_at_iso });
}

const BROKEN_CLUE_INTERACTIONS = new Set(["rfid_punishment", "lock", "luck_failure"]);

function playResultCue(result, snap) {
  if (!sfx && !fx) return;
  if (snap && (snap.gm_won === true || snap.gm_won === "true")) {
    if (sfx) sfx.powerDown();
    if (fx) fx.glitch();
    return;
  }
  if (result.won) {
    if (sfx) sfx.victory();
    return;
  }
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
  if (msg.type === "game_started") playIntro(msg.snapshot);
  if (msg.type === "hello") {
    hideWheelModal();
    setActiveView(msg.snapshot);
    return;
  }
  if (
    msg.type === "game_started" ||
    msg.type === "code_result" ||
    msg.type === "luck_test" ||
    msg.type === "luck_test_passed" ||
    msg.type === "timer_expired" ||
    msg.type === "timer_restarted" ||
    msg.type === "bounty_collection_started" ||
    msg.type === "bounty_collection_complete" ||
    msg.type === "punishment_complete" ||
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
    if (msg.type === "timer_expired") {
      if (sfx) sfx.alarm(3);
      if (fx) fx.glitch();
      setBanner("Time's up — the punishment wheel spins!", "bad");
    }
    if (msg.type === "timer_restarted") {
      setBanner("All RFIDs scanned — the timer restarts!", "ok");
    }
    if (msg.type === "bounty_collection_complete") {
      setBanner("Batch complete — scan the reward badge for the next batch.", "ok");
    }
    if (msg.type === "trump_used") {
      hideWheelModal();
      setBanner(msg.message || "Skip badge — punishment skipped!", "ok");
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
  if (msg.type === "forced_minigame" && msg.url) {
    if (msg.gm_won) {
      hideWheelModal();
      if (sfx) sfx.powerDown();
      setBanner(msg.game_over_message || "The Gamemaster wins!", "bad");
      return;
    }
    if (msg.reason === "punishment_wheel") hideWheelModal();
    const scheduled = msg.reason === "three_clues" || msg.reason === "good_scan_bonus";
    const tone = scheduled ? "ok" : "bad";
    const text =
      msg.message ||
      (scheduled
        ? "Three working clues — the Gamemaster opens a minigame."
        : "The Gamemaster locks the room — your penance is a minigame.");
    setBanner(text, tone);
    window.setTimeout(() => {
      window.location.href = msg.url;
    }, 1200);
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
