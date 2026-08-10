"use strict";

const $ = (id) => document.getElementById(id);

// ---- shared helpers ------------------------------------------------------

let busyDepth = 0;

function busy(on, text) {
  busyDepth += on ? 1 : -1;
  if (busyDepth < 0) busyDepth = 0;
  if (text) $("busy-text").textContent = text;
  $("busy").hidden = busyDepth === 0;
}

function showError(message) {
  const el = $("error");
  el.textContent = message;
  el.className = "error";
  el.hidden = false;
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/** For "here's what to do next" — red is for things that went wrong. */
function showNotice(message) {
  const el = $("error");
  el.textContent = message;
  el.className = "notice";
  el.hidden = false;
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function clearError() {
  $("error").hidden = true;
}

class SessionLost extends Error {}

/** POST JSON and return the parsed body, or throw an Error carrying a
 *  message that is safe to show to someone non-technical. */
async function api(path, body, { raw = false, form = null } = {}) {
  let resp;
  try {
    resp = form
      ? await fetch(path, { method: "POST", body: form })
      : await fetch(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
  } catch {
    throw new Error(
      "Could not reach SuperRedactor on this computer. Make sure the program is " +
        "still running in your terminal window, then reload this page."
    );
  }
  if (!resp.ok) {
    let detail = `Something went wrong (error ${resp.status}).`;
    try {
      const parsed = await resp.json();
      // FastAPI validation errors put an array here; showing it raw
      // rendered as "[object Object]".
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
      else if (parsed && parsed.detail)
        detail =
          "That file or setting wasn't in the expected format. Try choosing " +
          "the file again.";
    } catch {
      /* keep the generic message */
    }
    if (resp.status === 404) throw new SessionLost(detail);
    throw new Error(detail);
  }
  return raw ? resp.blob() : resp.json();
}

/** Wraps an action with the busy overlay and one consistent error path. */
function guard(text, fn, onSessionLost) {
  return async (...args) => {
    clearError();
    busy(true, text);
    try {
      await fn(...args);
    } catch (e) {
      if (e instanceof SessionLost) {
        showError(
          "That file is no longer loaded — this happens if SuperRedactor was " +
            "restarted. Please choose your file again."
        );
        if (onSessionLost) onSessionLost();
      } else {
        showError(e.message);
      }
    } finally {
      busy(false);
    }
  };
}

function setupDropzone(zoneId, inputId, onFile) {
  const zone = $(zoneId);
  const input = $(inputId);
  const open = () => input.click();
  zone.addEventListener("click", open);
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open();
    }
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

function sizeHint(file) {
  const mb = file.size / (1024 * 1024);
  return mb > 20
    ? `Reading ${Math.round(mb)} MB — large files can take a moment…`
    : "Reading your file…";
}

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return api("/api/upload", null, { form });
}

function downloadBlob(blob, filename) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 30000);
}

function renderSheetTabs(holderId, sheets, activeIndex, onPick) {
  const holder = $(holderId);
  holder.innerHTML = "";
  if (!sheets || sheets.length < 2) return;
  sheets.forEach((sheet, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sheet-tab" + (i === activeIndex ? " is-active" : "");
    btn.textContent = sheet.name;
    btn.addEventListener("click", () => onPick(i));
    holder.appendChild(btn);
  });
}

/** Says how many columns are off to the right, so "check every column"
 *  is actually possible to follow. */
function updateScrollHint(tableId, hintId, headers) {
  const hint = $(hintId);
  if (!hint) return;
  const scroller = $(tableId).closest(".table-scroll");
  const hidden = scroller && scroller.scrollWidth > scroller.clientWidth + 4;
  hint.textContent = hidden
    ? `${headers.length} columns — scroll sideways in the table to see them all.`
    : "";
}

function renderTable(tableId, headers, rows) {
  const table = $(tableId);
  table.innerHTML = "";
  const headRow = document.createElement("tr");
  for (const header of headers) {
    const th = document.createElement("th");
    th.textContent = header;
    headRow.appendChild(th);
  }
  table.appendChild(headRow);
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.appendChild(td);
    }
    table.appendChild(tr);
  }
}

// ---- tabs ----------------------------------------------------------------

function showPanel(panelId) {
  for (const tab of document.querySelectorAll(".tab")) {
    const active = tab.dataset.panel === panelId;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.hidden = panel.id !== panelId;
  }
  clearError();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => showPanel(tab.dataset.panel));
}

// ==========================================================================
// REDACT
// ==========================================================================

const state = {
  sessionId: null,
  filename: null,
  sheets: [],
  types: {},
  activeSheet: 0,
  config: {},
};

function adoptForRedact(body) {
  state.sessionId = body.session_id;
  state.filename = body.filename;
  state.sheets = body.sheets;
  state.types = body.redaction_types;
  state.activeSheet = 0;
  state.config = {};
  for (const sheet of body.sheets) {
    state.config[sheet.name] = { ...sheet.suggestions };
  }
  state.downloaded = false;
  // Splitting on the wrong character puts the first record in the heading
  // row, and headings are never replaced.
  const odd = body.sheets.find((s) => s.maybe_wrong_delimiter);
  if (odd) {
    const shown = { ",": "commas", "|": "vertical bars", ";": "semicolons", "\t": "tabs" }[
      odd.maybe_wrong_delimiter
    ];
    showNotice(
      `Check the column headings below. This file may really be separated by ` +
        `${shown} — if the headings look like a row of your data rather than ` +
        `names of columns, the first record will not be replaced. Re-save the ` +
        `file as a normal CSV and try again.`
    );
  }
  $("dropzone").hidden = true;
  $("workspace").hidden = false;
  $("redact-next").hidden = true;
  $("redact-warnings").innerHTML = "";
  $("file-label").textContent = body.filename;
  renderRedactTabs();
  renderRedactTable();
}

function renderRedactTabs() {
  renderSheetTabs("sheet-tabs", state.sheets, state.activeSheet, (i) => {
    state.activeSheet = i;
    renderRedactTabs();
    renderRedactTable();
  });
}

setupDropzone(
  "dropzone",
  "file-input",
  guard("Reading your file…", async (file) => {
    busy(true, sizeHint(file));
    try {
      adoptForRedact(await uploadFile(file));
    } finally {
      busy(false);
    }
  })
);

$("reset-btn").addEventListener("click", () => {
  state.sessionId = null;
  $("file-input").value = "";
  $("workspace").hidden = true;
  $("dropzone").hidden = false;
  clearError();
});

function renderRedactTable() {
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
    select.setAttribute("aria-label", `What to do with the column ${header}`);
    select.append(new Option("Keep as is", ""));
    const group = document.createElement("optgroup");
    group.label = "Replace with fake…";
    for (const [id, label] of Object.entries(state.types)) {
      group.append(new Option(label, id));
    }
    select.append(group);
    select.append(new Option("Remove this column", "drop"));
    select.value = action || "";
    if (action && action !== "drop") select.classList.add("is-redacting");
    select.addEventListener("change", () => {
      if (select.value) config[header] = select.value;
      else delete config[header];
      renderRedactTable();
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

  let redacted = 0;
  let dropped = 0;
  for (const cols of Object.values(state.config)) {
    for (const action of Object.values(cols)) {
      if (action === "drop") dropped += 1;
      else redacted += 1;
    }
  }
  const parts = [];
  if (redacted) parts.push(`${redacted} column${redacted === 1 ? "" : "s"} will be replaced with fake data`);
  if (dropped) parts.push(`${dropped} will be removed`);
  const sheetNote = state.sheets.length > 1 ? " (across all sheets)" : "";
  $("redact-summary").textContent = parts.length
    ? parts.join(", ") + sheetNote
    : "Nothing marked yet — choose at least one column to replace or remove.";
  $("redact-btn").disabled = !parts.length;

  updateScrollHint("preview-table", "redact-scroll-hint", sheet.headers);
  scheduleRedactCheck();
}

/** Checking for leftovers means scanning the file, so it waits for the
 *  user to stop changing dropdowns. */
let redactCheckTimer = null;
let redactCheckToken = 0;
function scheduleRedactCheck() {
  clearTimeout(redactCheckTimer);
  redactCheckTimer = setTimeout(runRedactCheck, 350);
}

async function runRedactCheck() {
  // The scan takes seconds on a large file, so two can be in flight at
  // once. Only the newest may draw — otherwise a slow earlier reply can
  // paint a stale all-clear over a fresh warning.
  const token = ++redactCheckToken;
  const isStale = () => token !== redactCheckToken;
  const holder = $("redact-warnings");
  if (!state.sessionId || $("redact-btn").disabled) {
    holder.innerHTML = "";
    return;
  }
  // On a large file the scan takes a couple of seconds. Say so, rather
  // than leaving an empty pane that reads like an all-clear.
  const checking = document.createElement("p");
  checking.className = "hint";
  checking.textContent = "Checking whether any values you are replacing appear elsewhere…";
  holder.innerHTML = "";
  holder.appendChild(checking);

  let body;
  try {
    body = await api("/api/redact/check", {
      session_id: state.sessionId,
      config: state.config,
    });
  } catch {
    if (isStale()) return;
    // A failed check must not look like a clean one — silence is the only
    // all-clear this screen gives.
    holder.innerHTML = "";
    const p = document.createElement("p");
    p.className = "warning-strip";
    p.textContent =
      "Could not check this file for leftover values just now. Change a " +
      "column to try again, or choose your file again.";
    holder.appendChild(p);
    return;
  }
  if (isStale()) return;
  holder.innerHTML = "";

  if (!body.leaks.length && !body.weak_columns.length) {
    const p = document.createElement("p");
    p.className = "all-clear";
    p.textContent =
      "Checked: none of the values you are replacing appear in the columns " +
      "you are keeping.";
    holder.appendChild(p);
  }

  for (const leak of body.leaks) {
    const p = document.createElement("p");
    p.className = "danger-note";
    const examples = leak.samples.map((s) => `"${s}"`).join(", ");
    p.textContent =
      `Still visible: "${leak.kept_column}" shows values from ` +
      `"${leak.redacted_column}" ${leak.partial ? "at least " : ""}${leak.count} ` +
      `time${leak.count === 1 ? "" : "s"} — for example ${examples}. ` +
      `Replace or remove "${leak.kept_column}" too, or those values go out with the file.`;
    holder.appendChild(p);
  }

  const manySheets = state.sheets.length > 1;
  for (const weak of body.weak_columns) {
    const p = document.createElement("p");
    p.className = "warning-strip";
    const where = manySheets ? ` on sheet "${weak.sheet}"` : "";
    p.textContent =
      `"${weak.column}"${where} has too few different values to hide anyone — ` +
      `some replacements will be values that really appear in this file. ` +
      `Removing the column is safer.`;
    holder.appendChild(p);
  }
}

$("redact-btn").addEventListener(
  "click",
  guard(
    "Redacting…",
    async () => {
      const blob = await api(
        "/api/redact",
        { session_id: state.sessionId, config: state.config },
        { raw: true }
      );
      const stem = state.filename.replace(/\.[^.]+$/, "");
      downloadBlob(blob, `${stem}.redacted-plus-key-DO-NOT-SHARE.zip`);
      $("redact-next").hidden = false;
      if (state.downloaded) {
        showNotice(
          "Downloaded again. The same file with the same choices always " +
            "produces the same fake values, so this pair works exactly like " +
            "the first one. Change a column and you get a different pair."
        );
      }
      state.downloaded = true;
    },
    () => {
      $("workspace").hidden = true;
      $("dropzone").hidden = false;
    }
  )
);

// ==========================================================================
// CLEAN UP
// ==========================================================================

const cleanState = {
  sessionId: null,
  filename: null,
  findings: [],
  enabled: new Set(),
  sheets: [],
  activeSheet: 0,
};

function resetClean() {
  $("clean-file-input").value = "";
  $("clean-workspace").hidden = true;
  $("clean-dropzone").hidden = false;
}

async function adoptForClean(body) {
  cleanState.sessionId = body.session_id;
  cleanState.filename = body.filename;
  const data = await api("/api/clean/analyze", { session_id: body.session_id });
  cleanState.findings = data.findings;
  cleanState.enabled = new Set(
    data.findings.filter((f) => !f.always).map((f) => f.id)
  );
  cleanState.activeSheet = 0;
  $("clean-dropzone").hidden = true;
  $("clean-workspace").hidden = false;
  $("clean-file-label").textContent = body.filename;
  renderFindings();
  renderCleanPreview(data.sheets);
}

setupDropzone(
  "clean-dropzone",
  "clean-file-input",
  guard("Reading your file…", async (file) => {
    busy(true, sizeHint(file));
    try {
      await adoptForClean(await uploadFile(file));
    } finally {
      busy(false);
    }
  })
);

$("clean-reset-btn").addEventListener("click", () => {
  cleanState.sessionId = null;
  resetClean();
  clearError();
});

function renderFindings() {
  const holder = $("clean-findings");
  holder.innerHTML = "";
  if (!cleanState.findings.length) {
    const p = document.createElement("p");
    p.className = "all-clear";
    p.textContent = "Good news — no problems found. This file already looks tidy.";
    holder.appendChild(p);
    $("clean-summary").textContent = "The download will match the file you gave us.";
    return;
  }
  const multiSheet = new Set(cleanState.findings.map((f) => f.sheet)).size > 1;
  for (const finding of cleanState.findings) {
    const label = document.createElement("label");
    label.className =
      "finding" +
      (finding.always ? " is-always" : cleanState.enabled.has(finding.id) ? "" : " is-off");

    let box;
    if (finding.always) {
      box = document.createElement("span");
      box.className = "lock";
      box.textContent = "🔒";
      box.title = "Applied to every download";
    } else {
      box = document.createElement("input");
      box.type = "checkbox";
      box.checked = cleanState.enabled.has(finding.id);
      box.addEventListener(
        "change",
        guard("Updating preview…", async () => {
          if (box.checked) cleanState.enabled.add(finding.id);
          else cleanState.enabled.delete(finding.id);
          label.classList.toggle("is-off", !box.checked);
          await refreshCleanPreview();
        }, resetClean)
      );
    }

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
  const optional = cleanState.findings.filter((f) => !f.always);
  const locked = cleanState.findings.length - optional.length;
  const on = optional.filter((f) => cleanState.enabled.has(f.id)).length;
  if (optional.length) {
    $("clean-summary").textContent = `${on} of ${optional.length} fixes will be applied`;
  } else if (locked) {
    $("clean-summary").textContent =
      "Only the locked fix above will be applied — everything else is unchanged.";
  } else {
    $("clean-summary").textContent = "The download will match the file you gave us.";
  }
}

async function refreshCleanPreview() {
  const body = await api("/api/clean/analyze", {
    session_id: cleanState.sessionId,
    enabled: [...cleanState.enabled],
  });
  renderCleanPreview(body.sheets);
  renderCleanSummary();
}

function renderCleanPreview(previewSheets) {
  cleanState.sheets = previewSheets;
  if (cleanState.activeSheet >= previewSheets.length) cleanState.activeSheet = 0;
  renderSheetTabs("clean-sheet-tabs", previewSheets, cleanState.activeSheet, (i) => {
    cleanState.activeSheet = i;
    renderCleanPreview(cleanState.sheets);
  });
  const sheet = previewSheets[cleanState.activeSheet];
  renderTable("clean-preview-table", sheet.headers, sheet.preview_rows);
}

$("clean-btn").addEventListener(
  "click",
  guard(
    "Cleaning…",
    async () => {
      const blob = await api(
        "/api/clean/apply",
        { session_id: cleanState.sessionId, enabled: [...cleanState.enabled] },
        { raw: true }
      );
      const stem = cleanState.filename.replace(/\.[^.]+$/, "");
      const ext = cleanState.filename.toLowerCase().endsWith(".xlsx") ? "xlsx" : "csv";
      downloadBlob(blob, `${stem}.cleaned.${ext}`);
    },
    resetClean
  )
);

async function commitClean() {
  return api("/api/clean/commit", {
    session_id: cleanState.sessionId,
    enabled: [...cleanState.enabled],
  });
}

$("clean-to-redact").addEventListener(
  "click",
  guard("Preparing…", async () => {
    adoptForRedact(await commitClean());
    showPanel("panel-redact");
  }, resetClean)
);

$("clean-to-standardize").addEventListener(
  "click",
  guard("Preparing…", async () => {
    const staged = await commitClean();
    showPanel("panel-standardize");
    setStdMode("apply");
    if (stdState.template) {
      stdState.pendingSession = null;
      await startStandardizeApply(staged);
    } else {
      stdState.pendingSession = staged;
      showNotice(
        "Your cleaned data is ready. Choose your template file above and it " +
          "will be standardized with it."
      );
    }
  }, resetClean)
);

// ==========================================================================
// STANDARDIZE
// ==========================================================================

const stdState = {
  makeSessionId: null,
  makeSheets: [],
  makeActiveSheet: 0,
  template: null,
  applySessionId: null,
  applyFilename: null,
  applySheets: [],
  applyActiveSheet: 0,
  mapping: {},
  extras: [],
  keepExtras: new Set(),
  sourceHeaders: [],
  vocabularies: {},
  pendingSession: null,
};

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

async function loadTemplateSource(body) {
  stdState.makeSessionId = body.session_id;
  stdState.makeSheets = body.sheets;
  stdState.makeActiveSheet = 0;
  $("std-make-dropzone").hidden = true;
  $("std-make-workspace").hidden = false;
  $("std-make-label").textContent = body.filename;
  await refreshTemplateFromSheet();
}

async function refreshTemplateFromSheet() {
  const sheetName = stdState.makeSheets[stdState.makeActiveSheet].name;
  const body = await api("/api/standardize/template", {
    session_id: stdState.makeSessionId,
    sheet: sheetName,
  });
  // Kept apart from the template so the saved file can never carry them.
  stdState.template = body.template;
  stdState.candidates = body.suggested_values || {};
  renderSheetTabs(
    "std-make-sheet-tabs",
    stdState.makeSheets,
    stdState.makeActiveSheet,
    guard("Reading sheet…", async (i) => {
      stdState.makeActiveSheet = i;
      await refreshTemplateFromSheet();
    })
  );
  renderTemplateColumns();
}

setupDropzone(
  "std-make-dropzone",
  "std-make-input",
  guard("Reading your file…", async (file) => {
    busy(true, sizeHint(file));
    try {
      await loadTemplateSource(await uploadFile(file));
    } finally {
      busy(false);
    }
  })
);

$("std-make-reset").addEventListener("click", () => {
  $("std-make-input").value = "";
  $("std-make-workspace").hidden = true;
  $("std-make-dropzone").hidden = false;
  clearError();
});

function renderTemplateColumns() {
  const remembered = stdState.template.columns.filter((c) => c.values);
  const warning = $("std-values-warning");
  warning.innerHTML = "";
  if (remembered.length) {
    const p = document.createElement("p");
    p.className = "warning-strip";
    p.textContent =
      `This template will now include real values copied from your file: ` +
      `${remembered.map((c) => `"${c.name}"`).join(", ")}. ` +
      `Only keep them if you are willing to share those values with anyone ` +
      `you give the template to.`;
    warning.appendChild(p);
  }
  $("std-make-summary").textContent = remembered.length
    ? "Check the remembered values above, then save."
    : "Save this as a template file you can reuse or share.";

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
    select.setAttribute("aria-label", `What ${col.name} holds`);
    for (const [value, label] of [
      ["text", "Text"],
      ["date", "Dates"],
      ["number", "Numbers"],
    ]) {
      select.append(new Option(label, value));
    }
    select.value = col.type;
    select.addEventListener("change", () => {
      col.type = select.value;
      if (col.type !== "text") delete col.values;
      renderTemplateColumns();
    });

    row.append(name, select);

    // Remembering a column's values copies real data into a file meant to
    // be shared, so it is off until asked for.
    const candidates = stdState.candidates || {};
    if (col.type === "text" && candidates[col.name]) {
      const label = document.createElement("label");
      label.className = "keep-label";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = Boolean(col.values);
      box.addEventListener("change", () => {
        if (box.checked) col.values = candidates[col.name].slice();
        else delete col.values;
        renderTemplateColumns();
      });
      label.append(box, "remember its values");
      const vocab = document.createElement("span");
      vocab.className = "vocab-note";
      vocab.textContent = col.values
        ? `remembering: ${col.values.join(", ")}`
        : `would remember: ${candidates[col.name].join(", ")}`;
      row.append(label, vocab);
    }
    holder.appendChild(row);
  }
}

$("std-save-template").addEventListener("click", () => {
  const name = stdState.template.name || "template";
  const blob = new Blob([JSON.stringify(stdState.template, null, 2)], {
    type: "application/json",
  });
  downloadBlob(blob, `${name}.template.json`);
  $("std-use-now").hidden = false;
});

// Saved templates are usually wanted immediately; making the user find the
// file they just downloaded was a needless detour.
$("std-use-now").addEventListener("click", () => {
  setStdMode("apply");
  $("std-apply-dropzone").hidden = false;
  showNotice(
    `Using the "${stdState.template.name}" template you just made. Drop in the ` +
      `file you want to standardize.`
  );
});

// --- apply a template ---

$("std-template-input").addEventListener(
  "change",
  guard("Reading template…", async () => {
    const file = $("std-template-input").files[0];
    if (!file) return;
    let parsed;
    const reject = (message) => {
      // Leaving the rejected name in the picker made it look like that file
      // was in use when the previous template still was.
      $("std-template-input").value = "";
      throw new Error(message);
    };
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      reject(
        "That file isn't a template. Templates are made on the 'Make a template' " +
          "screen and their names end in .template.json"
      );
    }
    if (parsed && parsed.mapping) {
      reject(
        "That's a key file from a redaction, not a template. Templates are made " +
          "on the 'Make a template' screen."
      );
    }
    if (!parsed || parsed.kind !== "template" || !Array.isArray(parsed.columns)) {
      reject(
        "That JSON file isn't a SuperRedactor template. Use one you saved on the " +
          "'Make a template' screen."
      );
    }
    stdState.template = parsed;
    $("std-apply-dropzone").hidden = false;
    if (stdState.pendingSession) {
      const staged = stdState.pendingSession;
      stdState.pendingSession = null;
      await startStandardizeApply(staged);
    }
  })
);

async function startStandardizeApply(body) {
  stdState.applySessionId = body.session_id;
  stdState.applyFilename = body.filename;
  stdState.applySheets = body.sheets;
  stdState.applyActiveSheet = 0;
  $("std-apply-dropzone").hidden = true;
  $("std-apply-workspace").hidden = false;
  $("std-apply-label").textContent = `${body.filename} → ${stdState.template.name}`;
  await matchActiveSheet();
}

async function matchActiveSheet() {
  const sheet = stdState.applySheets[stdState.applyActiveSheet];
  stdState.sourceHeaders = sheet.headers;
  const match = await api("/api/standardize/match", {
    session_id: stdState.applySessionId,
    sheet: sheet.name,
    template: stdState.template,
  });
  stdState.mapping = match.mapping;
  stdState.extras = match.extras;
  stdState.suggestions = match.suggestions || {};
  stdState.keepExtras = new Set();
  renderSheetTabs(
    "std-apply-sheet-tabs",
    stdState.applySheets,
    stdState.applyActiveSheet,
    guard("Matching columns…", async (i) => {
      stdState.applyActiveSheet = i;
      await matchActiveSheet();
    })
  );
  renderMapping();
  await refreshStdPreview();
}

setupDropzone(
  "std-apply-dropzone",
  "std-apply-input",
  guard("Reading your file…", async (file) => {
    busy(true, sizeHint(file));
    try {
      await startStandardizeApply(await uploadFile(file));
    } finally {
      busy(false);
    }
  })
);

function resetStdApply() {
  $("std-apply-input").value = "";
  $("std-apply-workspace").hidden = true;
  $("std-apply-dropzone").hidden = false;
}

$("std-apply-reset").addEventListener("click", () => {
  resetStdApply();
  clearError();
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
    type.textContent = { text: "text", date: "dates", number: "numbers" }[col.type];

    const select = document.createElement("select");
    select.setAttribute("aria-label", `Which column becomes ${col.name}`);
    select.append(new Option("— nothing, leave empty —", ""));
    for (const header of stdState.sourceHeaders) {
      select.append(new Option(header, header));
    }
    select.value = source || "";
    select.addEventListener(
      "change",
      guard("Updating preview…", async () => {
        stdState.mapping[col.name] = select.value || null;
        recomputeExtras();
        renderMapping();
        await refreshStdPreview();
      }, resetStdApply)
    );

    row.append(target, type, select);

    const suggestion = !source && stdState.suggestions[col.name];
    if (suggestion) {
      const hint = document.createElement("button");
      hint.type = "button";
      hint.className = "btn-quiet suggestion";
      hint.textContent = `Did you mean "${suggestion}"?`;
      hint.addEventListener(
        "click",
        guard("Updating preview…", async () => {
          stdState.mapping[col.name] = suggestion;
          recomputeExtras();
          renderMapping();
          await refreshStdPreview();
        }, resetStdApply)
      );
      row.appendChild(hint);
    }
    holder.appendChild(row);
  }

  for (const extra of stdState.extras) {
    const row = document.createElement("div");
    row.className = "map-row is-extra";
    const target = document.createElement("span");
    target.className = "map-target";
    target.textContent = extra;
    const note = document.createElement("span");
    note.textContent = "not in your template — will be removed unless you keep it";
    note.style.flex = "1";
    const keep = document.createElement("label");
    keep.className = "keep-label";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = stdState.keepExtras.has(extra);
    box.addEventListener(
      "change",
      guard("Updating preview…", async () => {
        if (box.checked) stdState.keepExtras.add(extra);
        else stdState.keepExtras.delete(extra);
        await refreshStdPreview();
      }, resetStdApply)
    );
    keep.append(box, "keep it");
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

function stdPayload() {
  return {
    session_id: stdState.applySessionId,
    sheet: stdState.applySheets[stdState.applyActiveSheet].name,
    template: stdState.template,
    mapping: stdState.mapping,
    keep_extras: [...stdState.keepExtras],
  };
}

async function refreshStdPreview() {
  const body = await api("/api/standardize/preview", stdPayload());

  const warnings = $("std-warnings");
  warnings.innerHTML = "";
  for (const w of body.warnings) {
    const p = document.createElement("p");
    p.className = "warning-strip";
    p.textContent = w;
    warnings.appendChild(p);
  }

  renderUnmatchedValues(body.unmatched, body.vocabularies);
  renderTable("std-preview-table", body.headers, body.preview_rows);

  const total = stdState.template.columns.length;
  const mapped = Object.values(stdState.mapping).filter(Boolean).length;
  const empty = total - mapped;
  $("std-summary").textContent =
    `${mapped} of ${total} template columns matched, ${body.row_count} rows`;
  // Spell out the consequence on the button itself: downloading a file
  // whose columns are silently blank is the costly mistake here.
  $("std-download").textContent = empty
    ? `Download anyway — ${empty} column${empty === 1 ? "" : "s"} will be empty`
    : "Download standardized file";
  $("std-download").classList.toggle("is-risky", empty > 0);
}

/** Values that don't appear in a column's remembered list. The user assigns
 *  them; nothing is ever guessed, because look-alike values (active /
 *  inactive) can mean opposite things. */
function renderUnmatchedValues(unmatched, vocabularies) {
  const holder = $("std-values");
  holder.innerHTML = "";
  const names = Object.keys(unmatched || {});
  if (!names.length) return;

  const heading = document.createElement("p");
  heading.className = "hint";
  heading.innerHTML =
    "<strong>Unfamiliar values.</strong> These don't match the list your template " +
    "remembers. Leave them as they are, or say which value they should become.";
  holder.appendChild(heading);

  for (const column of names) {
    for (const value of unmatched[column]) {
      const row = document.createElement("div");
      row.className = "map-row is-missing";
      const label = document.createElement("span");
      label.className = "map-target";
      label.textContent = `${column}: ${value}`;

      const select = document.createElement("select");
      select.setAttribute("aria-label", `What ${value} should become in ${column}`);
      select.append(new Option("— leave as it is —", ""));
      for (const canonical of vocabularies[column] || []) {
        select.append(new Option(`change to "${canonical}"`, canonical));
      }
      select.addEventListener(
        "change",
        guard("Updating preview…", async () => {
          const col = stdState.template.columns.find((c) => c.name === column);
          col.aliases = col.aliases || {};
          if (select.value) col.aliases[value] = select.value;
          else delete col.aliases[value];
          await refreshStdPreview();
        }, resetStdApply)
      );

      row.append(label, select);
      holder.appendChild(row);
    }
  }
}

$("std-download").addEventListener(
  "click",
  guard(
    "Standardizing…",
    async () => {
      const blob = await api("/api/standardize/apply", stdPayload(), { raw: true });
      const stem = stdState.applyFilename.replace(/\.[^.]+$/, "");
      const ext = stdState.applyFilename.toLowerCase().endsWith(".xlsx") ? "xlsx" : "csv";
      downloadBlob(blob, `${stem}.standardized.${ext}`);
    },
    resetStdApply
  )
);

$("std-to-redact").addEventListener(
  "click",
  guard("Preparing…", async () => {
    adoptForRedact(await api("/api/standardize/commit", stdPayload()));
    showPanel("panel-redact");
  }, resetStdApply)
);

$("std-to-clean").addEventListener(
  "click",
  guard("Preparing…", async () => {
    await adoptForClean(await api("/api/standardize/commit", stdPayload()));
    showPanel("panel-clean");
  }, resetStdApply)
);

// ==========================================================================
// RESTORE REAL VALUES
// ==========================================================================

$("deredact-btn").addEventListener(
  "click",
  guard("Restoring…", async () => {
    const file = $("mapping-input").files[0];
    if (!file) {
      throw new Error(
        "First choose the key file (mapping.json) that came in the ZIP with your " +
          "redacted file."
      );
    }
    const text = $("deredact-in").value;
    if (!text.trim()) {
      throw new Error("Paste the AI's answer into the box first.");
    }
    let mapping;
    try {
      mapping = JSON.parse(await file.text());
    } catch {
      throw new Error(
        "That file isn't the key file. Look for mapping.json inside the ZIP you " +
          "downloaded when you redacted."
      );
    }
    const body = await api("/api/deredact", { mapping, text });
    if (body.replacements === 0) {
      // Leaving the unchanged text in the box invites copying fake values
      // in the belief they are real.
      $("deredact-out").value = "";
      $("copy-btn").hidden = true;
      throw new Error(
        "Nothing in that text matched this key file, so there is nothing to " +
          "restore. Check you are using the key from the same redaction run as " +
          "the file you gave the AI."
      );
    }
    $("deredact-out").value = body.text;
    $("copy-btn").hidden = false;
  })
);

$("copy-btn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("deredact-out").value);
    $("copy-btn").textContent = "Copied";
    setTimeout(() => {
      $("copy-btn").textContent = "Copy";
    }, 1500);
  } catch {
    showError("Your browser blocked copying. Select the text and copy it manually.");
  }
});
