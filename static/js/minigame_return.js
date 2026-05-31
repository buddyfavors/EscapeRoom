(function () {
  "use strict";

  const params = new URLSearchParams(window.location.search);
  const forced = params.get("forced") === "1";
  const reason = params.get("reason") || "punishment";

  function isForced() {
    return forced;
  }

  function reasonLabel() {
    if (reason === "bonus" || reason === "three_clues") return "scheduled";
    return "punishment";
  }

  let overlay = null;
  let returnTimer = null;
  let countdownTimer = null;
  let countdownEl = null;
  let headlineEl = null;

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.className = "mg-return-overlay";
    overlay.innerHTML = `
      <div class="mg-return-card">
        <div class="mg-return-kicker">Minigame complete</div>
        <div class="mg-return-headline"></div>
        <div class="mg-return-countdown"><span class="mg-return-num">60</span><span class="mg-return-unit">s</span></div>
        <div class="mg-return-hint">Returning to the escape room…</div>
        <button type="button" class="mg-return-skip">Return now</button>
      </div>
    `;
    document.body.appendChild(overlay);
    headlineEl = overlay.querySelector(".mg-return-headline");
    countdownEl = overlay.querySelector(".mg-return-num");
    overlay.querySelector(".mg-return-skip").addEventListener("click", returnNow);
    return overlay;
  }

  function returnNow() {
    if (returnTimer) window.clearTimeout(returnTimer);
    if (countdownTimer) window.clearInterval(countdownTimer);
    returnTimer = null;
    countdownTimer = null;
    if (forced && reason === "punishment") {
      fetch("/api/game/punishment-complete", { method: "POST" }).finally(() => {
        window.location.href = "/";
      });
      return;
    }
    window.location.href = "/";
  }

  function scheduleReturn(opts) {
    if (!isForced()) return;
    opts = opts || {};
    const seconds = Math.max(5, Math.floor(opts.seconds || 60));
    const headline =
      opts.headline ||
      (reason === "three_clues" || reason === "bonus" ? "Nice run!" : "Game over.");
    ensureOverlay();
    if (headlineEl) headlineEl.textContent = headline;
    let remaining = seconds;
    if (countdownEl) countdownEl.textContent = String(remaining);
    if (returnTimer) window.clearTimeout(returnTimer);
    if (countdownTimer) window.clearInterval(countdownTimer);
    countdownTimer = window.setInterval(() => {
      remaining -= 1;
      if (remaining < 0) remaining = 0;
      if (countdownEl) countdownEl.textContent = String(remaining);
    }, 1000);
    returnTimer = window.setTimeout(returnNow, seconds * 1000);
  }

  function markForcedUi() {
    if (!isForced()) return;
    document.body.classList.add("mg-forced");
    // Hide navigation tabs so players can't wander out of the forced game.
    document.querySelectorAll(".nav a").forEach((a) => {
      a.setAttribute("hidden", "");
    });
    const endBtn = document.getElementById("nav-end-game");
    if (endBtn) endBtn.setAttribute("hidden", "");
    const ribbon = document.createElement("div");
    ribbon.className = "mg-forced-ribbon";
    ribbon.textContent =
      reason === "three_clues"
        ? "Scheduled minigame (after 3 good RFID codes) — finish to return to the escape room."
        : reason === "bonus"
          ? "Bonus challenge — finish to return to the escape room."
          : "Gamemaster challenge — finish to return to the escape room.";
    document.body.appendChild(ribbon);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", markForcedUi);
  } else {
    markForcedUi();
  }

  window.MinigameReturn = {
    isForced: isForced,
    scheduleReturn: scheduleReturn,
    returnNow: returnNow,
    reason: reasonLabel,
  };
})();
