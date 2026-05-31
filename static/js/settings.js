const ta = document.getElementById("codes-text");
const taRfid = document.getElementById("rfid-text");
const btnSave = document.getElementById("btn-save");
const btnReload = document.getElementById("btn-reload");
const btnSaveRfid = document.getElementById("btn-save-rfid");
const btnReloadRfid = document.getElementById("btn-reload-rfid");
const taPun = document.getElementById("punishments-text");
const btnSavePun = document.getElementById("btn-save-punishments");
const btnReloadPun = document.getElementById("btn-reload-punishments");
const saveMsg = document.getElementById("save-msg");
const saveMsgRfid = document.getElementById("save-msg-rfid");
const saveMsgPun = document.getElementById("save-msg-punishments");
const gmPre = document.getElementById("gm-snapshot");
const gmProgramming = document.getElementById("gm-programming");
const btnGm = document.getElementById("btn-refresh-gm");
const gmNameInput = document.getElementById("gm-name");
const badPhrasesText = document.getElementById("bad-phrases-text");
const wildcardGoodTag = document.getElementById("wildcard-good-tag");
const wildcardTrumpTag = document.getElementById("wildcard-trump-tag");
const btnSaveRoom = document.getElementById("btn-save-room");
const btnReloadRoom = document.getElementById("btn-reload-room");
const saveMsgRoom = document.getElementById("save-msg-room");

function setSaveMsg(el, text, ok) {
  el.textContent = text || "";
  el.classList.remove("ok", "bad");
  if (ok === true) el.classList.add("ok");
  if (ok === false) el.classList.add("bad");
}

async function loadCodes() {
  const res = await fetch("/api/codes");
  const data = await res.json();
  ta.value = data.text || "";
}

async function loadRfid() {
  const res = await fetch("/api/rfid-tags");
  const data = await res.json();
  taRfid.value = data.text || "";
}

async function loadPunishments() {
  const res = await fetch("/api/punishments");
  const data = await res.json();
  if (taPun) taPun.value = data.text || "";
  return data;
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

btnSave.addEventListener("click", async () => {
  btnSave.disabled = true;
  try {
    await postJson("/api/codes", { text: ta.value });
    setSaveMsg(saveMsg, "Lock codes saved.", true);
  } catch (e) {
    setSaveMsg(saveMsg, String(e.message || e), false);
  } finally {
    btnSave.disabled = false;
  }
});

btnReload.addEventListener("click", async () => {
  await loadCodes();
  setSaveMsg(saveMsg, "Lock codes reloaded from disk.", true);
});

btnSaveRfid.addEventListener("click", async () => {
  btnSaveRfid.disabled = true;
  try {
    const data = await postJson("/api/rfid-tags", { text: taRfid.value });
    const count = typeof data.count === "number" ? data.count : null;
    const removed = typeof data.duplicates_removed === "number" ? data.duplicates_removed : 0;
    let msg =
      count != null ? `Saved ${count} unique tag${count === 1 ? "" : "s"}.` : "RFID tags saved.";
    if (removed > 0) {
      msg += ` Removed ${removed} duplicate line${removed === 1 ? "" : "s"} from the list.`;
    }
    setSaveMsg(saveMsgRfid, msg, true);
    if (removed > 0) await loadRfid();
  } catch (e) {
    setSaveMsg(saveMsgRfid, String(e.message || e), false);
  } finally {
    btnSaveRfid.disabled = false;
  }
});

btnReloadRfid.addEventListener("click", async () => {
  await loadRfid();
  setSaveMsg(saveMsgRfid, "RFID tags reloaded from disk.", true);
});

if (btnSavePun) {
  btnSavePun.addEventListener("click", async () => {
    btnSavePun.disabled = true;
    try {
      const data = await postJson("/api/punishments", { text: taPun.value });
      const count = typeof data.count === "number" ? data.count : null;
      setSaveMsg(
        saveMsgPun,
        count != null
          ? `Saved ${count} punishment${count === 1 ? "" : "s"} on the wheel.`
          : "Wheel saved.",
        true,
      );
    } catch (e) {
      setSaveMsg(saveMsgPun, String(e.message || e), false);
    } finally {
      btnSavePun.disabled = false;
    }
  });
}

if (btnReloadPun) {
  btnReloadPun.addEventListener("click", async () => {
    const data = await loadPunishments();
    const count = typeof data.count === "number" ? data.count : null;
    setSaveMsg(
      saveMsgPun,
      count != null
        ? `Reloaded ${count} punishment${count === 1 ? "" : "s"}.`
        : "Wheel reloaded from disk.",
      true,
    );
  });
}

async function refreshGm() {
  const res = await fetch("/api/gm/snapshot");
  const data = await res.json();
  if (gmPre) gmPre.textContent = JSON.stringify(data, null, 2);

  if (!gmProgramming) return;
  if (!data.active || !data.programming || !data.programming.length) {
    gmProgramming.innerHTML = "<p>No active game — start one from the Play screen.</p>";
    gmProgramming.classList.add("muted");
    return;
  }

  const pct = data.rfid_good_percent != null ? data.rfid_good_percent : "—";
  const diff = data.snapshot && data.snapshot.difficulty ? data.snapshot.difficulty : "";
  const diffTitle = diff ? diff[0].toUpperCase() + diff.slice(1) : "—";

  let html =
    `<p class="gm-meta"><strong>RFID luck:</strong> ${diffTitle} · ${pct}% good scans · ` +
    `<strong>${data.programming.length}</strong> lock${data.programming.length === 1 ? "" : "s"}</p>` +
    '<table class="gm-table"><thead><tr><th>#</th><th>Type</th><th>Set lock to</th></tr></thead><tbody>';

  for (const row of data.programming) {
    html += `<tr><td>${row.index}</td><td>${row.kind_label}</td><td class="gm-code">${row.code}</td></tr>`;
  }
  html += "</tbody></table>";
  gmProgramming.innerHTML = html;
  gmProgramming.classList.remove("muted");
}

async function loadRoomSettings() {
  const res = await fetch("/api/room-settings");
  const data = await res.json();
  if (gmNameInput) gmNameInput.value = data.gamemaster_name || "Gamemaster";
  if (badPhrasesText) {
    badPhrasesText.value = (data.bad_scan_phrases || []).join("\n");
  }
  if (wildcardGoodTag) wildcardGoodTag.value = data.wildcard_free_good_tag || "";
  if (wildcardTrumpTag) wildcardTrumpTag.value = data.wildcard_trump_tag || "";
}

if (btnSaveRoom) {
  btnSaveRoom.addEventListener("click", async () => {
    btnSaveRoom.disabled = true;
    try {
      const phrases = (badPhrasesText?.value || "")
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      if (!phrases.length) {
        throw new Error("Add at least one bad-scan phrase.");
      }
      await postJson("/api/room-settings", {
        gamemaster_name: (gmNameInput?.value || "Gamemaster").trim(),
        bad_scan_phrases: phrases,
        wildcard_free_good_tag: (wildcardGoodTag?.value || "").trim() || null,
        wildcard_trump_tag: (wildcardTrumpTag?.value || "").trim() || null,
      });
      setSaveMsg(saveMsgRoom, "Room settings saved.", true);
    } catch (e) {
      setSaveMsg(saveMsgRoom, String(e.message || e), false);
    } finally {
      btnSaveRoom.disabled = false;
    }
  });
}

if (btnReloadRoom) {
  btnReloadRoom.addEventListener("click", async () => {
    await loadRoomSettings();
    setSaveMsg(saveMsgRoom, "Room settings reloaded.", true);
  });
}

btnGm.addEventListener("click", refreshGm);

loadCodes();
loadRfid();
loadPunishments();
loadRoomSettings();
refreshGm();
