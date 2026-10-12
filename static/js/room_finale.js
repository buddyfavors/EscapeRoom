/**
 * Victory finale on the play screen: white-out flash, fanfare, confetti and fireworks,
 * and the CRT typing out that the prisoner is free, followed by stats for the run.
 */
(function (global) {
  const sounds = () => global.RoomSounds;

  const overlay = document.getElementById("finale-overlay");
  const textRoot = document.getElementById("finale-text");
  const statsEl = document.getElementById("finale-stats");
  const canvas = document.getElementById("finale-confetti");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const FLASH_MS = 700;
  const TYPE_DELAY_MS = 900;
  const CHAR_MS = 34;
  const LINE_PAUSE_MS = 650;
  const CELEBRATE_MS = 9000;

  let shownFor = null;
  let lines = [];
  let typing = false;
  let timers = [];

  function later(fn, ms) {
    timers.push(window.setTimeout(fn, ms));
  }

  function clearTimers() {
    timers.forEach((t) => window.clearTimeout(t));
    timers = [];
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function escapeTargets(snap) {
    const locks = snap.locks || [];
    const boxes = locks.filter((l) => l.kind === "digit4");
    return { targets: boxes.length ? boxes : locks, noun: boxes.length ? "lockbox" : "lock" };
  }

  function formatDuration(startIso, endIso) {
    const start = Date.parse(startIso || "");
    const end = Date.parse(endIso || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "—";
    const s = Math.floor((end - start) / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
  }

  function renderText(snap) {
    const gm = escapeHtml((snap && snap.gamemaster_name) || "The Gamemaster");
    const { noun } = escapeTargets(snap);
    textRoot.innerHTML = `
      <p class="crt-hello" data-type>…Impossible.</p>
      <h2 id="finale-title" class="crt-title" data-type>The prisoner is free.</h2>
      <p data-type>Every ${noun} lies open. The restraints fall away.</p>
      <p data-type><em>${gm}</em> swore no one would walk out of this room. Tonight, you proved otherwise.</p>
      <p class="crt-begin" data-type>Game over. You win.</p>
    `;
    lines = Array.from(textRoot.querySelectorAll("[data-type]")).map((el) => {
      const nodes = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        nodes.push({ node: walker.currentNode, full: walker.currentNode.nodeValue.replace(/\s+/g, " ") });
      }
      return { el, nodes };
    });
  }

  function renderStats(snap) {
    const locks = snap.locks || [];
    const { targets, noun } = escapeTargets(snap);
    const opened = targets.filter((l) => l.solved).length;
    const clues = locks.reduce(
      (n, l) => n + (l.clues || []).filter((c) => c != null && c !== "").length,
      0
    );
    const items = [
      ["Escape time", formatDuration(snap.started_at_iso, snap.finished_at_iso)],
      [noun === "lockbox" ? "Lockboxes opened" : "Locks opened", `${opened} / ${targets.length}`],
      ["Clues recovered", String(clues)],
      ["Punishments endured", String(Math.max(0, Number(snap.punishments_received) || 0))],
    ];
    statsEl.innerHTML = items
      .map(
        ([label, value]) =>
          `<div class="finale-stat"><span class="finale-stat-value">${escapeHtml(value)}</span>` +
          `<span class="finale-stat-label">${escapeHtml(label)}</span></div>`
      )
      .join("");
  }

  function hideText() {
    for (const line of lines) {
      line.el.style.visibility = "hidden";
      for (const n of line.nodes) n.node.nodeValue = "";
    }
  }

  function revealAll() {
    for (const line of lines) {
      line.el.classList.remove("typing");
      line.el.style.visibility = "";
      for (const n of line.nodes) n.node.nodeValue = n.full;
    }
  }

  function finish() {
    typing = false;
    clearTimers();
    revealAll();
    overlay.classList.add("finale-done");
  }

  function typeLines() {
    typing = true;
    let li = 0;
    let ni = 0;
    let ci = 0;
    let tick = 0;
    function step() {
      if (!typing) return;
      if (li >= lines.length) {
        finish();
        return;
      }
      const line = lines[li];
      line.el.style.visibility = "";
      line.el.classList.add("typing");
      const n = line.nodes[ni];
      if (!n) {
        line.el.classList.remove("typing");
        li += 1;
        ni = 0;
        ci = 0;
        later(step, LINE_PAUSE_MS);
        return;
      }
      ci += 1;
      n.node.nodeValue = n.full.slice(0, ci);
      tick += 1;
      if (tick % 3 === 0 && n.full[ci - 1] !== " " && sounds()) sounds().typeTick();
      if (ci >= n.full.length) {
        ni += 1;
        ci = 0;
      }
      later(step, CHAR_MS);
    }
    step();
  }

  function flash() {
    if (reducedMotion) return;
    document.body.classList.remove("fx-victory");
    void document.body.offsetWidth;
    document.body.classList.add("fx-victory");
    later(() => document.body.classList.remove("fx-victory"), 1200);
  }

  /* Confetti + fireworks on a full-screen canvas. */

  const COLORS = ["#e9b65c", "#8cff9e", "#4fc3b6", "#f1e3bf", "#ff6b5e", "#fff0cc"];
  const MAX_PARTICLES = 650;
  const ctx = canvas ? canvas.getContext("2d") : null;
  let particles = [];
  let rafId = null;
  let lastTs = 0;
  let celebrateUntil = 0;
  let nextBurstAt = 0;
  let width = 0;
  let height = 0;

  function pick(list) {
    return list[Math.floor(Math.random() * list.length)];
  }

  function resizeCanvas() {
    if (!canvas || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function spawnConfetti(count, fromAbove) {
    for (let i = 0; i < count && particles.length < MAX_PARTICLES; i++) {
      particles.push({
        kind: "confetti",
        x: Math.random() * width,
        y: fromAbove ? -20 - Math.random() * height * 0.5 : -20,
        vx: (Math.random() - 0.5) * 80,
        vy: 60 + Math.random() * 120,
        rot: Math.random() * Math.PI * 2,
        vr: (Math.random() - 0.5) * 10,
        flip: Math.random() * Math.PI * 2,
        size: 7 + Math.random() * 8,
        color: pick(COLORS),
        age: 0,
      });
    }
  }

  function spawnBurst() {
    const cx = width * (0.12 + Math.random() * 0.76);
    const cy = height * (0.1 + Math.random() * 0.35);
    const color = pick(COLORS);
    const count = 70;
    for (let i = 0; i < count && particles.length < MAX_PARTICLES; i++) {
      const angle = (i / count) * Math.PI * 2 + Math.random() * 0.2;
      const speed = 140 + Math.random() * 300;
      particles.push({
        kind: "spark",
        x: cx,
        y: cy,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: 2 + Math.random() * 2.5,
        color: Math.random() < 0.25 ? "#ffffff" : color,
        life: 1.1 + Math.random() * 0.7,
        age: 0,
      });
    }
  }

  function stepParticle(p, dt) {
    p.age += dt;
    if (p.kind === "spark") {
      p.vx *= 0.975;
      p.vy = p.vy * 0.975 + 170 * dt;
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      if (p.age >= p.life) return false;
      ctx.globalAlpha = Math.max(0, 1 - p.age / p.life);
      ctx.fillStyle = p.color;
      ctx.fillRect(p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
      return true;
    }
    p.vy = Math.min(260, p.vy + 220 * dt);
    p.x += (p.vx + Math.sin(p.age * 3 + p.flip) * 40) * dt;
    p.y += p.vy * dt;
    p.rot += p.vr * dt;
    p.flip += 6 * dt;
    if (p.y > height + 30) return false;
    ctx.globalAlpha = 1;
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.rot);
    ctx.scale(1, Math.cos(p.flip));
    ctx.fillStyle = p.color;
    ctx.fillRect(-p.size / 2, -p.size * 0.3, p.size, p.size * 0.6);
    ctx.restore();
    return true;
  }

  function frame(ts) {
    const dt = lastTs ? Math.min(0.05, (ts - lastTs) / 1000) : 1 / 60;
    lastTs = ts;
    const now = performance.now();
    const celebrating = now < celebrateUntil;
    if (celebrating) {
      if (now >= nextBurstAt) {
        spawnBurst();
        nextBurstAt = now + 450 + Math.random() * 650;
      }
      spawnConfetti(2, false);
    }
    ctx.clearRect(0, 0, width, height);
    particles = particles.filter((p) => stepParticle(p, dt));
    ctx.globalAlpha = 1;
    if (celebrating || particles.length) {
      rafId = window.requestAnimationFrame(frame);
    } else {
      rafId = null;
    }
  }

  function startCelebration() {
    if (!ctx || reducedMotion) return;
    resizeCanvas();
    particles = [];
    spawnConfetti(160, true);
    celebrateUntil = performance.now() + CELEBRATE_MS;
    nextBurstAt = 0;
    lastTs = 0;
    if (!rafId) rafId = window.requestAnimationFrame(frame);
  }

  function stopCelebration() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = null;
    particles = [];
    celebrateUntil = 0;
    if (ctx) ctx.clearRect(0, 0, width, height);
  }

  function show(snap) {
    if (!overlay || !textRoot || !snap) return;
    const key = snap.started_at_iso || "finale";
    if (key === shownFor) return;
    shownFor = key;
    clearTimers();
    typing = false;
    renderText(snap);
    renderStats(snap);
    hideText();
    overlay.classList.remove("finale-done", "closing");

    flash();
    if (sounds()) sounds().fanfare();
    later(() => {
      overlay.hidden = false;
      startCelebration();
      later(typeLines, TYPE_DELAY_MS);
    }, reducedMotion ? 0 : FLASH_MS);
  }

  function close() {
    if (!overlay) return;
    clearTimers();
    typing = false;
    stopCelebration();
    document.body.classList.remove("fx-victory");
    overlay.hidden = true;
    overlay.classList.remove("finale-done");
  }

  if (overlay) {
    overlay.addEventListener("click", (ev) => {
      if (typing && !ev.target.closest("button")) finish();
    });
    document.addEventListener("keydown", (ev) => {
      if (overlay.hidden || !typing) return;
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        finish();
      }
    });
    window.addEventListener("resize", () => {
      if (rafId) resizeCanvas();
    });
  }

  global.RoomFinale = { show, close };
})(window);
