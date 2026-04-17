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
const btnGm = document.getElementById("btn-refresh-gm");

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
    setSaveMsg(saveMsgRfid, count != null ? `Saved ${count} tag${count === 1 ? "" : "s"}.` : "RFID tags saved.", true);
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
  gmPre.textContent = JSON.stringify(data, null, 2);
}

btnGm.addEventListener("click", refreshGm);

loadCodes();
loadRfid();
loadPunishments();
refreshGm();
