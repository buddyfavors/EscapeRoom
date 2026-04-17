/* global use: mountArcadeGrid(root, onPress) -> { clearAll, setReactionTarget, setWhackMoles } */
(function (global) {
  const COLOR_CLASSES = ["color-0", "color-1", "color-2", "color-3", "color-4"];
  const COLUMN_NAMES = ["Green", "Blue", "White", "Yellow", "Red"];

  function mountArcadeGrid(root, onPress) {
    const byId = new Map();
    const grid = document.createElement("div");
    grid.className = "arcade-grid";

    for (let c = 0; c < 5; c++) {
      const col = document.createElement("div");
      col.className = "arcade-column";
      for (let s = 0; s < 3; s++) {
        const id = c * 3 + s;
        const b = document.createElement("button");
        b.type = "button";
        b.className = "arcade-btn dim " + COLOR_CLASSES[c];
        b.dataset.buttonId = String(id);
        b.textContent = String(s + 1);
        b.title = COLUMN_NAMES[c] + " button " + (s + 1) + " (id " + id + ")";
        b.addEventListener("click", () => onPress(id));
        byId.set(id, b);
        col.appendChild(b);
      }
      grid.appendChild(col);
    }
    root.appendChild(grid);

    function clearAll() {
      for (const b of byId.values()) {
        b.classList.add("dim");
        b.classList.remove("lit", "target", "safe", "trap");
      }
    }

    function setReactionTarget(targetId) {
      clearAll();
      const b = byId.get(targetId);
      if (b) {
        b.classList.remove("dim");
        b.classList.add("lit", "target");
      }
    }

    function setWhackMoles(moles) {
      clearAll();
      for (const m of moles || []) {
        const b = byId.get(m.i);
        if (!b) continue;
        b.classList.remove("dim");
        b.classList.add("lit", m.trap ? "trap" : "safe");
      }
    }

    return { clearAll, setReactionTarget, setWhackMoles, grid };
  }

  global.mountArcadeGrid = mountArcadeGrid;
})(window);
