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

// ---- clean up ------------------------------------------------------------

const cleanState = {
  sessionId: null,
  filename: null,
  findings: [],       // from /api/clean/analyze
  enabled: new Set(), // finding ids currently checked
  sheets: [],         // latest preview sheets
  activeSheet: 0,
};

const cleanDropzone = $("clean-dropzone");
const cleanFileInput = $("clean-file-input");

cleanDropzone.addEventListener("click", () => cleanFileInput.click());
cleanDropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") cleanFileInput.click();
});
cleanDropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  cleanDropzone.classList.add("is-over");
});
cleanDropzone.addEventListener("dragleave", () => cleanDropzone.classList.remove("is-over"));
cleanDropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  cleanDropzone.classList.remove("is-over");
  if (e.dataTransfer.files.length) cleanUpload(e.dataTransfer.files[0]);
});
cleanFileInput.addEventListener("change", () => {
  if (cleanFileInput.files.length) cleanUpload(cleanFileInput.files[0]);
});

async function cleanUpload(file) {
  clearError();
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/upload", { method: "POST", body: form });
  if (!resp.ok) return showError(await apiError(resp));
  const body = await resp.json();
  cleanState.sessionId = body.session_id;
  cleanState.filename = body.filename;

  const analysis = await fetch("/api/clean/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: cleanState.sessionId }),
  });
  if (!analysis.ok) return showError(await apiError(analysis));
  const data = await analysis.json();
  cleanState.findings = data.findings;
  cleanState.enabled = new Set(data.findings.map((f) => f.id));

  cleanDropzone.hidden = true;
  $("clean-workspace").hidden = false;
  $("clean-file-label").textContent = body.filename;
  renderFindings();
  renderCleanPreview(data.sheets);
}

$("clean-reset-btn").addEventListener("click", () => {
  cleanState.sessionId = null;
  cleanFileInput.value = "";
  $("clean-workspace").hidden = true;
  cleanDropzone.hidden = false;
  clearError();
});

function renderFindings() {
  const holder = $("clean-findings");
  holder.innerHTML = "";
  if (!cleanState.findings.length) {
    const p = document.createElement("p");
    p.className = "all-clear";
    p.textContent = "No problems found — this file already looks tidy.";
    holder.appendChild(p);
    $("clean-summary").textContent = "The download will match the original.";
    return;
  }
  const multiSheet = new Set(cleanState.findings.map((f) => f.sheet)).size > 1;
  for (const finding of cleanState.findings) {
    const label = document.createElement("label");
    label.className = "finding" + (cleanState.enabled.has(finding.id) ? "" : " is-off");

    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = cleanState.enabled.has(finding.id);
    box.addEventListener("change", async () => {
      if (box.checked) cleanState.enabled.add(finding.id);
      else cleanState.enabled.delete(finding.id);
      label.classList.toggle("is-off", !box.checked);
      await refreshCleanPreview();
    });

    const bodyEl = document.createElement("div");
    bodyEl.className = "finding-body";
    const desc = document.createElement("div");
    desc.className = "finding-desc";
    desc.textContent = finding.description;
    if (multiSheet) {
      const sheetSpan = document.createElement("span");
      sheetSpan.className = "finding-sheet";
      sheetSpan.textContent = ` — sheet "${finding.sheet}"`;
      desc.appendChild(sheetSpan);
    }
    bodyEl.appendChild(desc);
    if (finding.samples.length) {
      const samples = document.createElement("p");
      samples.className = "finding-samples";
      finding.samples.forEach(([before, after], i) => {
        if (i) samples.append("   ");
        samples.append(before + " ");
        const arrow = document.createElement("span");
        arrow.className = "arrow";
        arrow.textContent = "→";
        samples.append(arrow, " " + after);
      });
      bodyEl.appendChild(samples);
    }

    label.append(box, bodyEl);
    holder.appendChild(label);
  }
  renderCleanSummary();
}

function renderCleanSummary() {
  const on = cleanState.enabled.size;
  const total = cleanState.findings.length;
  $("clean-summary").textContent = total
    ? `${on} of ${total} fixes selected`
    : "The download will match the original.";
}

async function refreshCleanPreview() {
  const resp = await fetch("/api/clean/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: cleanState.sessionId,
      enabled: [...cleanState.enabled],
    }),
  });
  if (!resp.ok) return showError(await apiError(resp));
  renderCleanPreview((await resp.json()).sheets);
  renderCleanSummary();
}

function renderCleanPreview(previewSheets) {
  cleanState.sheets = previewSheets;
  if (cleanState.activeSheet >= previewSheets.length) cleanState.activeSheet = 0;

  const tabs = $("clean-sheet-tabs");
  tabs.innerHTML = "";
  if (previewSheets.length > 1) {
    previewSheets.forEach((s, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sheet-tab" + (i === cleanState.activeSheet ? " is-active" : "");
      btn.textContent = s.name;
      btn.addEventListener("click", () => {
        cleanState.activeSheet = i;
        renderCleanPreview(cleanState.sheets);
      });
      tabs.appendChild(btn);
    });
  }

  const table = $("clean-preview-table");
  table.innerHTML = "";
  const sheet = previewSheets[cleanState.activeSheet];
  const headRow = document.createElement("tr");
  for (const header of sheet.headers) {
    const th = document.createElement("th");
    th.textContent = header;
    headRow.appendChild(th);
  }
  table.appendChild(headRow);
  for (const row of sheet.preview_rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.appendChild(td);
    }
    table.appendChild(tr);
  }
}

$("clean-btn").addEventListener("click", async () => {
  clearError();
  const resp = await fetch("/api/clean/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: cleanState.sessionId,
      enabled: [...cleanState.enabled],
    }),
  });
  if (!resp.ok) return showError(await apiError(resp));
  const blob = await resp.blob();
  const stem = cleanState.filename.replace(/\.[^.]+$/, "");
  const ext = cleanState.filename.toLowerCase().endsWith(".xlsx") ? "xlsx" : "csv";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${stem}.cleaned.${ext}`;
  link.click();
  URL.revokeObjectURL(link.href);
});

// ---- standardize ---------------------------------------------------------

const stdState = {
  // make mode
  makeSessionId: null,
  makeFilename: null,
  template: null,      // template being built (make) or loaded (apply)
  // apply mode
  applySessionId: null,
  applyFilename: null,
  mapping: {},         // template column -> source header | null
  extras: [],          // unmatched source headers
  keepExtras: new Set(),
  sourceHeaders: [],
};

function setupDropzone(zoneId, inputId, onFile) {
  const zone = $(zoneId);
  const input = $(inputId);
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") input.click();
  });
  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("is-over");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("is-over");
    if (e.dataTransfer.files.length) onFile(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files.length) onFile(input.files[0]);
  });
}

async function uploadForSession(file) {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch("/api/upload", { method: "POST", body: form });
  if (!resp.ok) throw new Error(await apiError(resp));
  return resp.json();
}

// mode toggle
$("std-mode-make").addEventListener("click", () => setStdMode("make"));
$("std-mode-apply").addEventListener("click", () => setStdMode("apply"));

function setStdMode(mode) {
  $("std-mode-make").classList.toggle("is-active", mode === "make");
  $("std-mode-apply").classList.toggle("is-active", mode === "apply");
  $("std-make").hidden = mode !== "make";
  $("std-apply").hidden = mode !== "apply";
  clearError();
}

// --- make a template ---

setupDropzone("std-make-dropzone", "std-make-input", async (file) => {
  clearError();
  try {
    const body = await uploadForSession(file);
    stdState.makeSessionId = body.session_id;
    stdState.makeFilename = body.filename;
    const resp = await fetch("/api/standardize/template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: body.session_id }),
    });
    if (!resp.ok) return showError(await apiError(resp));
    stdState.template = await resp.json();
    $("std-make-dropzone").hidden = true;
    $("std-make-workspace").hidden = false;
    $("std-make-label").textContent = body.filename;
    renderTemplateColumns();
  } catch (e) {
    showError(e.message);
  }
});

$("std-make-reset").addEventListener("click", () => {
  $("std-make-input").value = "";
  $("std-make-workspace").hidden = true;
  $("std-make-dropzone").hidden = false;
});

function renderTemplateColumns() {
  const holder = $("std-columns");
  holder.innerHTML = "";
  for (const col of stdState.template.columns) {
    const row = document.createElement("div");
    row.className = "map-row";
    const name = document.createElement("span");
    name.className = "map-target";
    name.textContent = col.name;
    const select = document.createElement("select");
    select.className = "type-select";
    select.setAttribute("aria-label", `Type for ${col.name}`);
    for (const t of ["text", "date", "number"]) {
      select.append(new Option(t, t));
    }
    select.value = col.type;
    select.addEventListener("change", () => { col.type = select.value; });
    row.append(name, select);
    holder.appendChild(row);
  }
}

$("std-save-template").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(stdState.template, null, 2)], {
    type: "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${stdState.template.name}.template.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

// --- apply a template ---

$("std-template-input").addEventListener("change", async () => {
  clearError();
  const file = $("std-template-input").files[0];
  if (!file) return;
  try {
    stdState.template = JSON.parse(await file.text());
  } catch {
    return showError("That file isn't valid JSON — expected a template.json.");
  }
  if (stdState.template.kind !== "template" || !Array.isArray(stdState.template.columns)) {
    return showError("That JSON doesn't look like a SuperRedactor template.");
  }
  $("std-apply-dropzone").hidden = false;
});

setupDropzone("std-apply-dropzone", "std-apply-input", async (file) => {
  clearError();
  try {
    const body = await uploadForSession(file);
    stdState.applySessionId = body.session_id;
    stdState.applyFilename = body.filename;
    stdState.sourceHeaders = body.sheets[0].headers;
    const resp = await fetch("/api/standardize/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: body.session_id,
        template: stdState.template,
      }),
    });
    if (!resp.ok) return showError(await apiError(resp));
    const match = await resp.json();
    stdState.mapping = match.mapping;
    stdState.extras = match.extras;
    stdState.keepExtras = new Set();
    $("std-apply-dropzone").hidden = true;
    $("std-apply-workspace").hidden = false;
    $("std-apply-label").textContent = `${file.name} → ${stdState.template.name} template`;
    renderMapping();
    await refreshStdPreview();
  } catch (e) {
    showError(e.message);
  }
});

$("std-apply-reset").addEventListener("click", () => {
  $("std-apply-input").value = "";
  $("std-apply-workspace").hidden = true;
  $("std-apply-dropzone").hidden = false;
});

function renderMapping() {
  const holder = $("std-mapping");
  holder.innerHTML = "";

  for (const col of stdState.template.columns) {
    const source = stdState.mapping[col.name];
    const row = document.createElement("div");
    row.className = "map-row" + (source ? "" : " is-missing");

    const target = document.createElement("span");
    target.className = "map-target";
    target.textContent = col.name;
    const type = document.createElement("span");
    type.className = "map-type";
    type.textContent = col.type;

    const select = document.createElement("select");
    select.setAttribute("aria-label", `Source column for ${col.name}`);
    select.append(new Option("— leave empty —", ""));
    for (const header of stdState.sourceHeaders) {
      select.append(new Option(header, header));
    }
    select.value = source || "";
    select.addEventListener("change", async () => {
      stdState.mapping[col.name] = select.value || null;
      recomputeExtras();
      renderMapping();
      await refreshStdPreview();
    });

    row.append(target, type, select);
    holder.appendChild(row);
  }

  for (const extra of stdState.extras) {
    const row = document.createElement("div");
    row.className = "map-row is-extra";
    const target = document.createElement("span");
    target.className = "map-target";
    target.textContent = extra;
    const note = document.createElement("span");
    note.textContent = "not in template — dropped unless kept";
    note.style.flex = "1";
    const keep = document.createElement("label");
    keep.className = "keep-label";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = stdState.keepExtras.has(extra);
    box.addEventListener("change", async () => {
      if (box.checked) stdState.keepExtras.add(extra);
      else stdState.keepExtras.delete(extra);
      await refreshStdPreview();
    });
    keep.append(box, "keep");
    row.append(target, note, keep);
    holder.appendChild(row);
  }
}

function recomputeExtras() {
  const used = new Set(Object.values(stdState.mapping).filter(Boolean));
  stdState.extras = stdState.sourceHeaders.filter((h) => !used.has(h));
  for (const kept of [...stdState.keepExtras]) {
    if (!stdState.extras.includes(kept)) stdState.keepExtras.delete(kept);
  }
}

async function refreshStdPreview() {
  const resp = await fetch("/api/standardize/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: stdState.applySessionId,
      template: stdState.template,
      mapping: stdState.mapping,
      keep_extras: [...stdState.keepExtras],
    }),
  });
  if (!resp.ok) return showError(await apiError(resp));
  const body = await resp.json();

  const warnings = $("std-warnings");
  warnings.innerHTML = "";
  for (const w of body.warnings) {
    const p = document.createElement("p");
    p.className = "warning-strip";
    p.textContent = w;
    warnings.appendChild(p);
  }

  const table = $("std-preview-table");
  table.innerHTML = "";
  const headRow = document.createElement("tr");
  for (const header of body.headers) {
    const th = document.createElement("th");
    th.textContent = header;
    headRow.appendChild(th);
  }
  table.appendChild(headRow);
  for (const row of body.preview_rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.appendChild(td);
    }
    table.appendChild(tr);
  }

  const mapped = Object.values(stdState.mapping).filter(Boolean).length;
  $("std-summary").textContent =
    `${mapped} of ${stdState.template.columns.length} template columns mapped, ` +
    `${body.row_count} rows`;
}

$("std-download").addEventListener("click", async () => {
  clearError();
  const resp = await fetch("/api/standardize/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: stdState.applySessionId,
      template: stdState.template,
      mapping: stdState.mapping,
      keep_extras: [...stdState.keepExtras],
    }),
  });
  if (!resp.ok) return showError(await apiError(resp));
  const blob = await resp.blob();
  const stem = stdState.applyFilename.replace(/\.[^.]+$/, "");
  const ext = stdState.applyFilename.toLowerCase().endsWith(".xlsx") ? "xlsx" : "csv";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${stem}.standardized.${ext}`;
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
