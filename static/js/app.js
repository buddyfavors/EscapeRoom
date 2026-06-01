const banner = document.getElementById("banner");
const setupError = document.getElementById("setup-error");
const locksEl = document.getElementById("locks");
const locksSection = document.getElementById("locks-section");
const btnPlay = document.getElementById("btn-play");
const overviewView = document.getElementById("overview-view");
const activeView = document.getElementById("active-view");
const activeModeLabel = document.getElementById("active-mode-label");
const activeDifficulty = document.getElementById("active-difficulty");
const activeSub = document.getElementById("active-sub");
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
const rfidNextBadEl = document.getElementById("rfid-next-bad");
const punishmentLimitInput = document.getElementById("punishment-limit");
const punishmentLimitEnabledInput = document.getElementById("punishment-limit-enabled");
const meterHint = document.getElementById("meter-hint");
const rewardsPill = document.getElementById("rewards-pill");
const rewardsCount = document.getElementById("rewards-count");
const bountyGoodPill = document.getElementById("bounty-good-pill");
const bountyGoodCount = document.getElementById("bounty-good-count");
const collectionPill = document.getElementById("collection-pill");
const collectionCount = document.getElementById("collection-count");
const modeBreakoutSettings = document.getElementById("mode-breakout-settings");
const modeDeadlineSettings = document.getElementById("mode-deadline-settings");
const modeBountySettings = document.getElementById("mode-bounty-settings");
const timerMinutesInput = document.getElementById("timer-minutes");
const rfidsPerPunishmentInput = document.getElementById("rfids-per-punishment");
const goodCodesPerRewardInput = document.getElementById("good-codes-per-reward");
const rewardsToWinInput = document.getElementById("rewards-to-win");
const finalCountdownEnabledInput = document.getElementById("final-countdown-enabled");
const finalCountdownStartAfterInput = document.getElementById("final-countdown-start-after");
const gmControls = document.getElementById("gm-controls");
const gmStatusLine = document.getElementById("gm-status-line");
const wheelModal = document.getElementById("wheel-modal");
const wheelSpinStage = document.getElementById("wheel-spin-stage");
const wheelResultStage = document.getElementById("wheel-result-stage");
const wheelSpinner = document.getElementById("wheel-spinner");
const wheelSpinLabel = document.getElementById("wheel-spin-label");
const wheelSpinText = document.getElementById("wheel-spin-text");
const wheelLastKicker = document.getElementById("wheel-last-kicker");
const wheelPunishmentLabel = document.getElementById("wheel-punishment-label");
const wheelPunishmentText = document.getElementById("wheel-punishment-text");
const wheelCountdownWrap = document.querySelector(".wheel-countdown");
const wheelCountdownNum = document.getElementById("wheel-countdown-num");
const wheelCountdownHint = document.getElementById("wheel-countdown-hint");
const wheelResultKicker = document.getElementById("wheel-result-kicker");

const lockInputs = {
  digit3: document.getElementById("lock-digit3"),
  letter5: document.getElementById("lock-letter5"),
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
const availLabels = {
  digit3: document.getElementById("avail-digit3"),
  letter5: document.getElementById("avail-letter5"),
  digit4: document.getElementById("avail-digit4"),
};
const gmPreviewEl = document.getElementById("gm-preview");

const MODE_LABELS = {
  breakout: "Breakout",
  deadline: "Deadline",
  bounty: "Bounty",
};

let setupData = null;
let previewTimer = null;
let timerTick = null;
let timerEndsAtMs = null;
let timerShrinkNote = "";
let timerCycle = 1;

const WHEEL_SPIN_MS = 4000;
let wheelModalOpen = false;
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

function punishmentFromPlainText(text) {
  const line = text != null ? String(text).trim() : "";
  if (!line) return null;
  if (line.includes(": ")) {
    const splitAt = line.indexOf(": ");
    return {
      label: line.slice(0, splitAt).trim(),
      message: line.slice(splitAt + 2).trim(),
    };
  }
  return { label: line, message: "" };
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

function setWheelSpinStageDisplay(lastPunishmentText) {
  const prior = punishmentFromPlainText(lastPunishmentText);
  const hasPrior = !!(prior && (prior.label || prior.message));
  if (wheelLastKicker) wheelLastKicker.hidden = !hasPrior;
  if (hasPrior) {
    applyWheelPunishmentDisplay(wheelSpinLabel, wheelSpinText, prior);
  } else {
    applyWheelPunishmentDisplay(wheelSpinLabel, wheelSpinText, null);
  }
}

function hideWheelModal() {
  wheelModalOpen = false;
  if (wheelModal) wheelModal.hidden = true;
  if (wheelSpinTimer) {
    window.clearTimeout(wheelSpinTimer);
    wheelSpinTimer = null;
  }
  setWheelSpinStageDisplay(null);
  stopPunishmentTimerTick();
}

function stopPunishmentTimerTick() {
  if (punishmentTimerTick) window.clearInterval(punishmentTimerTick);
  punishmentTimerTick = null;
  punishmentTimerEndsAtMs = null;
  punishmentTimerKind = null;
  if (wheelCountdownWrap) wheelCountdownWrap.hidden = true;
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
    if (wheelResultKicker) wheelResultKicker.textContent = "Your punishment";
    if (wheelCountdownHint) {
      wheelCountdownHint.textContent =
        "Scan your skip badge to skip, or scan the Gamemaster complete badge when done.";
    }
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

function showWheelModal(msg) {
  if (!wheelModal) return;
  wheelModalOpen = true;
  wheelModal.hidden = false;
  if (wheelSpinStage) wheelSpinStage.hidden = false;
  if (wheelResultStage) wheelResultStage.hidden = true;
  if (wheelCountdownWrap) wheelCountdownWrap.hidden = true;
  if (wheelResultKicker) wheelResultKicker.textContent = "Your punishment";
  setWheelSpinStageDisplay(msg.snapshot?.last_punishment);
  if (wheelSpinner) {
    wheelSpinner.classList.remove("spinning");
    void wheelSpinner.offsetWidth;
    wheelSpinner.classList.add("spinning");
  }
  if (wheelSpinTimer) window.clearTimeout(wheelSpinTimer);
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
  if (!wheelModalOpen) {
    wheelModalOpen = true;
    if (wheelModal) wheelModal.hidden = false;
    if (wheelSpinStage) wheelSpinStage.hidden = true;
    if (wheelResultStage) wheelResultStage.hidden = false;
    applyWheelPunishmentDisplay(wheelPunishmentLabel, wheelPunishmentText, {
      label: snap.pending_punishment_label,
      message: snap.pending_punishment_message,
    });
  }
  syncPunishmentTimerFromSnapshot(snap);
}

function lockPayload(counts) {
  return {
    digit3: counts.digit3,
    letter5: counts.letter5,
    digit4: counts.digit4,
  };
}

function gmName(snap) {
  return (snap && snap.gamemaster_name) || "Gamemaster";
}

function updateFinalCountdownInputs() {
  const on = !!(finalCountdownEnabledInput && finalCountdownEnabledInput.checked);
  if (finalCountdownStartAfterInput) finalCountdownStartAfterInput.disabled = !on;
}

function updatePunishmentLimitInputs() {
  const on = !!(punishmentLimitEnabledInput && punishmentLimitEnabledInput.checked);
  if (punishmentLimitInput) punishmentLimitInput.disabled = !on;
}

function selectedGameMode() {
  const el = document.querySelector('input[name="game_mode"]:checked');
  return el ? el.value : "breakout";
}

function selectedBountyTheme() {
  const el = document.querySelector('input[name="bounty_theme"]:checked');
  return el ? el.value : "breakout";
}

function updateModePanels() {
  const mode = selectedGameMode();
  if (modeBreakoutSettings) modeBreakoutSettings.hidden = mode !== "breakout";
  if (modeDeadlineSettings) modeDeadlineSettings.hidden = mode !== "deadline";
  if (modeBountySettings) modeBountySettings.hidden = mode !== "bounty";
  if (mode === "breakout") scheduleLockPreview();
  updateFinalCountdownInputs();
  updatePunishmentLimitInputs();
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

function renderTimerText() {
  if (!timerDisplay || timerEndsAtMs == null) return;
  const sec = Math.max(0, Math.floor((timerEndsAtMs - Date.now()) / 1000));
  timerDisplay.textContent = `Round ${timerCycle} · Time left: ${formatTimer(sec)}${timerShrinkNote}`;
  timerDisplay.classList.toggle("timer-urgent", sec <= 60);
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
  if (selectedGameMode() !== "breakout") return;
  if (previewTimer) window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => {
    previewTimer = null;
    refreshLockPreview();
  }, 350);
}

async function refreshLockPreview() {
  if (!gmPreviewEl || (overviewView && overviewView.hidden)) return;
  if (selectedGameMode() !== "breakout") return;
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
  if (!punishmentLimitEnabledInput?.checked) {
    return 0;
  }
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

function clampInput(input, min, max, fallback) {
  const n = Math.max(min, Math.min(max, parseInt(input?.value || String(fallback), 10) || fallback));
  if (input) input.value = String(n);
  return n;
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
      if (max === 0) label.textContent = "none available";
      else if (max === 1) label.textContent = "max 1";
      else label.textContent = `max ${max}`;
    }
    const buttons = lockStepButtons[kind];
    if (buttons && input) {
      const current = Math.max(0, parseInt(input.value, 10) || 0);
      if (buttons[-1]) buttons[-1].disabled = input.disabled || current <= 0;
      if (buttons[1]) buttons[1].disabled = input.disabled || current >= max;
    }
  }
  if (punishmentLimitInput && data.default_punishment_limit != null) {
    punishmentLimitInput.value = String(data.default_punishment_limit);
  }
  if (punishmentLimitEnabledInput) {
    punishmentLimitEnabledInput.checked = !!data.default_punishment_limit_enabled;
  }
  updatePunishmentLimitInputs();
  if (timerMinutesInput && data.default_timer_minutes != null) {
    timerMinutesInput.value = String(data.default_timer_minutes);
  }
  if (rfidsPerPunishmentInput && data.default_rfids_per_punishment != null) {
    rfidsPerPunishmentInput.value = String(data.default_rfids_per_punishment);
  }
  if (goodCodesPerRewardInput && data.default_good_codes_per_reward != null) {
    goodCodesPerRewardInput.value = String(data.default_good_codes_per_reward);
  }
  if (rewardsToWinInput && data.default_rewards_to_win != null) {
    rewardsToWinInput.value = String(data.default_rewards_to_win);
  }
  if (finalCountdownStartAfterInput && data.default_final_countdown_start_after != null) {
    finalCountdownStartAfterInput.value = String(data.default_final_countdown_start_after);
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

function badCodesHint(snap) {
  const effect = snap && snap.bad_code_effect;
  if (effect === "time_penalty") {
    return "Every 3rd bad code shaves 30 seconds off the clock.";
  }
  if (effect === "lose_progress") {
    return "Every 3rd bad code steals one step toward your next reward.";
  }
  return "Every 3rd bad RFID or wrong lock try spins the wheel.";
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
  const show = snap && snap.game_mode === "breakout";
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
  const show = mode === "deadline" && phase === "collection";
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
  if (snap.punishment_resolution === "trump_window") {
    parts.push("Punishment pending — skip badge or Gamemaster complete badge.");
  }
  const rewardCd = Math.max(0, Number(snap.wildcard_free_good_cooldown_seconds) || 0);
  if (rewardCd > 0) parts.push(`Reward badge cooldown: ${rewardCd}s.`);
  gmControls.hidden = parts.length === 0;
  if (gmStatusLine) gmStatusLine.textContent = parts.join(" ");
}

function renderPhaseBanner(snap) {
  if (!phaseBanner) return;
  if (!snap || snap.game_mode !== "deadline") {
    phaseBanner.hidden = true;
    phaseBanner.textContent = "";
    return;
  }
  const phase = snap.phase || "playing";
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
}

function renderMeterHint(snap) {
  if (!meterHint) return;
  if (!snap) {
    meterHint.textContent = "";
    return;
  }
  const mode = snap.game_mode || "breakout";
  if (mode === "deadline") {
    meterHint.textContent =
      "Deadline — survive each countdown. Timer punishments spin the wheel; bad codes shave 30 seconds instead.";
  } else if (mode === "bounty") {
    meterHint.textContent =
      `Bounty — earn ${snap.good_codes_per_reward || 5} good codes per reward, ` +
      `${snap.rewards_to_win || 5} rewards to win. ${badCodesHint(snap)}`;
  } else {
    meterHint.textContent =
      "Breakout — bad codes never reset; every 3rd bad code spins the wheel (no duplicate punishments).";
  }
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
    if (rfidNextBadEl) {
      rfidNextBadEl.hidden = true;
      rfidNextBadEl.textContent = "";
    }
    stopTimerTick();
    renderBadCodesMeter(null);
    renderPunishmentsMeter(null);
    renderClueMinigameMeter(null);
    renderBountyMeters(null);
    renderCollectionMeter(null);
    renderPhaseBanner(null);
    renderMeterHint(null);
    renderGmControls(null);
    hideWheelModal();
    updateModePanels();
    return;
  }

  const mode = snap.game_mode || "breakout";
  if (activeModeLabel) activeModeLabel.textContent = MODE_LABELS[mode] || "Game";
  if (activeSub) {
    if (mode === "deadline") {
      activeSub.textContent = `Beat the clock — punishments come when time runs out. Outlast ${gmName(snap)}.`;
    } else if (mode === "bounty") {
      activeSub.textContent = `Stack good scans into rewards before ${gmName(snap)} breaks your streak.`;
    } else {
      activeSub.textContent = `Scan clues, crack the locks, escape before ${gmName(snap)} wins.`;
    }
  }
  if (locksSection) locksSection.hidden = mode !== "breakout";

  renderBadCodesMeter(snap);
  renderPunishmentsMeter(snap);
  renderClueMinigameMeter(snap);
  renderBountyMeters(snap);
  renderCollectionMeter(snap);
  renderPhaseBanner(snap);
  renderMeterHint(snap);
  renderGmControls(snap);
  syncWheelModalFromSnapshot(snap);
  syncTimerFromSnapshot(snap);

  if (activeDifficulty) {
    const d = (snap.difficulty || "medium").toString();
    activeDifficulty.textContent = `— ${d[0].toUpperCase() + d.slice(1)}`;
  }
  if (rfidNextBadEl) {
    const pct = snap.rfid_bad_chance_percent != null ? snap.rfid_bad_chance_percent : null;
    const hide = pct == null || snap.game_over || snap.phase === "collection";
    if (!hide) {
      rfidNextBadEl.hidden = false;
      rfidNextBadEl.textContent = `Next badge scan: ${pct}% bad (rises after each good scan).`;
    } else {
      rfidNextBadEl.hidden = true;
      rfidNextBadEl.textContent = "";
    }
  }
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
    for (const lock of snap.locks || []) {
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
  if (inter === "rfid_collect" || inter === "rfid_good") return "ok";
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
  input.addEventListener("input", () => {
    scheduleLockPreview();
    setSetupError("");
  });
  input.addEventListener("change", () => {
    scheduleLockPreview();
    setSetupError("");
  });
}

for (const [kind, buttonsByDelta] of Object.entries(lockStepButtons)) {
  const input = lockInputs[kind];
  if (!input) continue;
  for (const [deltaStr, btn] of Object.entries(buttonsByDelta)) {
    const delta = Number(deltaStr);
    if (!btn || !Number.isFinite(delta)) continue;
    btn.addEventListener("click", () => {
      if (input.disabled) return;
      const max = parseInt(input.max || "0", 10) || 0;
      const current = parseInt(input.value || "0", 10) || 0;
      const next = Math.max(0, Math.min(max, current + delta));
      input.value = String(next);
      if (buttonsByDelta[-1]) buttonsByDelta[-1].disabled = input.disabled || next <= 0;
      if (buttonsByDelta[1]) buttonsByDelta[1].disabled = input.disabled || next >= max;
      scheduleLockPreview();
      setSetupError("");
    });
  }
}

document.querySelectorAll('input[name="game_mode"]').forEach((el) => {
  el.addEventListener("change", () => {
    updateModePanels();
    setSetupError("");
  });
});
if (finalCountdownEnabledInput) {
  finalCountdownEnabledInput.addEventListener("change", updateFinalCountdownInputs);
}
if (punishmentLimitEnabledInput) {
  punishmentLimitEnabledInput.addEventListener("change", updatePunishmentLimitInputs);
}

if (btnPlay) {
  btnPlay.addEventListener("click", async () => {
    const mode = selectedGameMode();
    const locks = selectedLockCounts();
    if (mode === "breakout" && locks.digit3 + locks.letter5 + locks.digit4 < 1) {
      const msg = "Pick at least one lock to start Breakout.";
      setSetupError(msg);
      setBanner(msg, "bad");
      return;
    }
    setSetupError("");
    btnPlay.disabled = true;
    try {
      const payload = {
        game_mode: mode,
        difficulty: selectedDifficulty(),
        digit3: locks.digit3,
        letter5: locks.letter5,
        digit4: locks.digit4,
      };
      if (mode === "breakout") {
        const punishmentLimit = selectedPunishmentLimit();
        if (punishmentLimit > 0) {
          payload.punishment_limit = punishmentLimit;
        }
      }
      if (mode === "deadline") {
        payload.timer_minutes = clampInput(timerMinutesInput, 1, 180, 10);
        payload.rfids_per_punishment = clampInput(rfidsPerPunishmentInput, 1, 99, 4);
        payload.final_countdown_enabled = !!(finalCountdownEnabledInput && finalCountdownEnabledInput.checked);
        if (payload.final_countdown_enabled) {
          payload.final_countdown_start_after = clampInput(
            finalCountdownStartAfterInput,
            1,
            99,
            3
          );
        }
      }
      if (mode === "bounty") {
        payload.good_codes_per_reward = clampInput(goodCodesPerRewardInput, 1, 99, 5);
        payload.rewards_to_win = clampInput(rewardsToWinInput, 1, 99, 5);
        payload.bounty_theme = selectedBountyTheme();
      }
      const data = await postJson("/api/game/start", payload);
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
  if (
    msg.type === "game_started" ||
    msg.type === "code_result" ||
    msg.type === "timer_expired" ||
    msg.type === "timer_restarted" ||
    msg.type === "punishment_complete" ||
    msg.type === "trump_used" ||
    msg.type === "punishment_wheel" ||
    msg.type === "punishment_resolved"
  ) {
    if (msg.snapshot) setActiveView(msg.snapshot);
    if (msg.type === "punishment_wheel") {
      showWheelModal(msg);
      setBanner("The wheel of punishments has spoken!", "bad");
      return;
    }
    if (msg.type === "code_result" && msg.result) {
      if (msg.snapshot && (msg.snapshot.gm_won === true || msg.snapshot.gm_won === "true")) {
        setBanner(
          `${gmName(msg.snapshot)} wins — you failed!`,
          "bad"
        );
      } else if (msg.result.won) {
        setBanner(msg.result.message, "ok");
      } else {
        setBanner(msg.result.message, bannerToneForResult(msg.result));
      }
    }
    if (msg.type === "timer_expired") {
      setBanner("Time's up — the punishment wheel spins!", "bad");
    }
    if (msg.type === "timer_restarted") {
      setBanner("All RFIDs scanned — the timer restarts!", "ok");
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
    setActiveView(null);
    setBanner("Game ended.", "");
    return;
  }
  if (msg.type === "forced_minigame" && msg.url) {
    if (msg.gm_won) {
      hideWheelModal();
      setBanner(msg.game_over_message || "The Gamemaster wins!", "bad");
      return;
    }
    if (msg.reason === "punishment_wheel") hideWheelModal();
    const scheduled = msg.reason === "three_clues" || msg.reason === "good_scan_bonus";
    const tone = scheduled ? "ok" : "bad";
    const text =
      msg.message ||
      (scheduled
        ? "Three good RFID codes — the Gamemaster opens a minigame."
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
    const text = msg.gm_won
      ? msg.game_over_message || "The Gamemaster wins!"
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
  updateModePanels();
  updateFinalCountdownInputs();
  updatePunishmentLimitInputs();
  try {
    const res = await fetch("/api/game/status");
    const data = await res.json();
    setActiveView(data.snapshot);
  } catch {
    /* offline */
  }
  connectWs();
})();
