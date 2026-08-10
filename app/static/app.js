"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  sessionId: null,
  filename: null,
  sheets: [],            // from /api/upload
  types: {},             // redaction type id -> label
  activeSheet: 0,
  config: {},            // {sheetName: {column: type | "drop"}}
};

// ---- tabs ----------------------------------------------------------------

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    for (const t of document.querySelectorAll(".tab")) {
      t.classList.toggle("is-active", t === tab);
      t.setAttribute("aria-selected", String(t === tab));
    }
    for (const p of document.querySelectorAll(".panel")) {
      p.hidden = p.id !== tab.dataset.panel;
    }
    clearError();
  });
}

// ---- errors --------------------------------------------------------------

function showError(message) {
  const el = $("error");
  el.textContent = message;
  el.hidden = false;
}
function clearError() { $("error").hidden = true; }

async function apiError(resp) {
  try {
    const body = await resp.json();
    return body.detail || `Request failed (${resp.status})`;
  } catch {
    return `Request failed (${resp.status})`;
  }
}

// ---- upload --------------------------------------------------------------

const dropzone = $("dropzone");
const fileInput = $("file-input");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});
dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("is-over");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-over"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("is-over");
  if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) uploadFile(fileInput.files[0]);
});

async function uploadFile(file) {
  clearError();
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/upload", { method: "POST", body: form });
  if (!resp.ok) return showError(await apiError(resp));
  const body = await resp.json();

  state.sessionId = body.session_id;
  state.filename = body.filename;
  state.sheets = body.sheets;
  state.types = body.redaction_types;
  state.activeSheet = 0;
  state.config = {};
  for (const sheet of body.sheets) {
    state.config[sheet.name] = { ...sheet.suggestions };
  }

  dropzone.hidden = true;
  $("workspace").hidden = false;
  $("file-label").textContent = body.filename;
  renderSheetTabs();
  renderTable();
}

$("reset-btn").addEventListener("click", () => {
  state.sessionId = null;
  fileInput.value = "";
  $("workspace").hidden = true;
  dropzone.hidden = false;
  clearError();
});

// ---- preview table -------------------------------------------------------

function renderSheetTabs() {
  const holder = $("sheet-tabs");
  holder.innerHTML = "";
  if (state.sheets.length < 2) return;
  state.sheets.forEach((sheet, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sheet-tab" + (i === state.activeSheet ? " is-active" : "");
    btn.textContent = sheet.name;
    btn.addEventListener("click", () => {
      state.activeSheet = i;
      renderSheetTabs();
      renderTable();
    });
    holder.appendChild(btn);
  });
}

function renderTable() {
  const sheet = state.sheets[state.activeSheet];
  const config = state.config[sheet.name];
  const table = $("preview-table");
  table.innerHTML = "";

  const headRow = document.createElement("tr");
  sheet.headers.forEach((header) => {
    const th = document.createElement("th");
    const action = config[header];
    if (action === "drop") th.classList.add("is-dropped");

    const wrap = document.createElement("div");
    wrap.className = "col-head";

    const name = document.createElement("span");
    name.className = "col-name";
    name.textContent = header;
    if (sheet.suggestions[header] && config[header] === sheet.suggestions[header]) {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "suggested";
      name.appendChild(badge);
    }

    const select = document.createElement("select");
    select.setAttribute("aria-label", `Action for column ${header}`);
    select.append(new Option("Keep as is", ""));
    const group = document.createElement("optgroup");
    group.label = "Redact as…";
    for (const [id, label] of Object.entries(state.types)) {
      group.append(new Option(label, id));
    }
    select.append(group);
    select.append(new Option("Drop column", "drop"));
    select.value = action || "";
    if (action && action !== "drop") select.classList.add("is-redacting");
    select.addEventListener("change", () => {
      if (select.value) config[header] = select.value;
      else delete config[header];
      renderTable();
    });

    wrap.append(name, select);
    th.appendChild(wrap);
    headRow.appendChild(th);
  });
  table.appendChild(headRow);

  for (const row of sheet.preview_rows) {
    const tr = document.createElement("tr");
    row.forEach((cell, i) => {
      const td = document.createElement("td");
      const action = config[sheet.headers[i]];
      if (action === "drop") {
        td.classList.add("is-dropped");
        td.textContent = cell;
      } else if (action && cell !== "") {
        const bar = document.createElement("span");
        bar.className = "cell-bar";
        bar.style.width = `${Math.max(2, Math.min(cell.length, 24)) * 0.55}em`;
        td.appendChild(bar);
      } else {
        td.textContent = cell;
      }
      tr.appendChild(td);
    });
    table.appendChild(tr);
  }

  renderSummary();
}

function renderSummary() {
  let redacted = 0;
  let dropped = 0;
  for (const cols of Object.values(state.config)) {
    for (const action of Object.values(cols)) {
      if (action === "drop") dropped += 1;
      else redacted += 1;
    }
  }
  const parts = [];
  if (redacted) parts.push(`${redacted} column${redacted === 1 ? "" : "s"} redacted`);
  if (dropped) parts.push(`${dropped} dropped`);
  $("redact-summary").textContent = parts.length
    ? parts.join(", ")
    : "No columns marked yet — everything would pass through unchanged.";
  $("redact-btn").disabled = !parts.length;
}

// ---- redact + download ---------------------------------------------------

$("redact-btn").addEventListener("click", async () => {
  clearError();
  const resp = await fetch("/api/redact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.sessionId, config: state.config }),
  });
  if (!resp.ok) return showError(await apiError(resp));
  const blob = await resp.blob();
  const stem = state.filename.replace(/\.[^.]+$/, "");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${stem}.redacted.zip`;
  link.click();
  URL.revokeObjectURL(link.href);
});

// ---- de-redact -----------------------------------------------------------

$("deredact-btn").addEventListener("click", async () => {
  clearError();
  const file = $("mapping-input").files[0];
  if (!file) return showError("Choose the mapping.json from your redaction run first.");
  const text = $("deredact-in").value;
  if (!text.trim()) return showError("Paste the AI output you want restored.");

  let mapping;
  try {
    mapping = JSON.parse(await file.text());
  } catch {
    return showError("That file isn't valid JSON — expected the mapping.json from the ZIP.");
  }

  const resp = await fetch("/api/deredact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mapping, text }),
  });
  if (!resp.ok) return showError(await apiError(resp));
  const body = await resp.json();
  $("deredact-out").value = body.text;
  $("copy-btn").hidden = false;
});

$("copy-btn").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("deredact-out").value);
  $("copy-btn").textContent = "Copied";
  setTimeout(() => { $("copy-btn").textContent = "Copy"; }, 1500);
});
