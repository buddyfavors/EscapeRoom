(function () {
  const btn = document.getElementById("nav-end-game");
  if (!btn) return;

  function setActive(active) {
    btn.hidden = !active;
  }
  window.NavSetGameActive = setActive;

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await fetch("/api/game/stop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } catch (e) {
      /* ignore */
    }
    setActive(false);
    btn.disabled = false;
    if (location.pathname !== "/") {
      location.href = "/";
    }
  });

  (async () => {
    try {
      const r = await fetch("/api/game/status");
      const d = await r.json();
      setActive(!!d.active);
    } catch {
      /* ignore */
    }
  })();
})();
