/**
 * MyMarkItDown Single-Page UI Application.
 */

import {
  classifyFile,
  filterByRecurse,
  generateZipFilename,
  resolveOutputNames,
  shouldSkipUnchanged,
  stripRootFolder,
} from "./plan.js";
import {
  collectFiles,
  getTargetLastModified,
  isFileSystemAccessSupported,
  pickDirectory,
  verifyReadWritePermission,
  writeFile as fsWriteFile,
} from "./fs-access.js";
import { createZipSink, loadJSZip } from "./zip-fallback.js";

// Application state
const state = {
  mode: "fs", // "fs" or "zip"
  formats: [],
  inputDirHandle: null,
  outputDirHandle: null,
  rawScannedFiles: [], // Raw items with relPath & file
  scannedItems: [], // Filtered & classified items
  isConverting: false,
  convertedMarkdownSingle: null,
};

// DOM elements
const el = {
  btnPickInput: document.getElementById("btn-pick-input"),
  inputFolderFile: document.getElementById("input-folder-file"),
  btnPickOutput: document.getElementById("btn-pick-output"),
  outputPickerContainer: document.getElementById("output-picker-container"),
  inputFolderName: document.getElementById("input-folder-name"),
  outputFolderName: document.getElementById("output-folder-name"),
  optRecurse: document.getElementById("opt-recurse"),
  optSkipUnchanged: document.getElementById("opt-skip-unchanged"),
  optFrontmatter: document.getElementById("opt-frontmatter"),
  btnConvert: document.getElementById("btn-convert"),
  planTitle: document.getElementById("plan-title"),
  planTbody: document.getElementById("plan-tbody"),
  progressContainer: document.getElementById("progress-container"),
  progressBar: document.getElementById("progress-bar"),
  progressText: document.getElementById("progress-text"),
  summaryCard: document.getElementById("summary-card"),
  statConverted: document.getElementById("stat-converted"),
  statSkipped: document.getElementById("stat-skipped"),
  statFailed: document.getElementById("stat-failed"),
  singleCopyArea: document.getElementById("single-copy-area"),
  btnCopyMarkdown: document.getElementById("btn-copy-markdown"),
  copyStatus: document.getElementById("copy-status"),
  fallbackNotice: document.getElementById("fallback-notice"),
  errorBanner: document.getElementById("error-banner"),
  pickerCard: document.getElementById("picker-card"),
};

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/**
 * Safely update a status table cell with a badge element using textContent to prevent XSS.
 */
function setStatus(cell, badgeClass, text, title = "") {
  if (!cell) return;
  cell.textContent = "";
  const span = document.createElement("span");
  span.className = `badge ${badgeClass}`;
  span.textContent = text;
  if (title) {
    span.title = title;
  }
  cell.appendChild(span);
}

/**
 * Factory for File System Access output sink.
 */
function createFsSink(outputDirHandle) {
  return {
    type: "fs",
    async writeFile(relFilePath, content) {
      await fsWriteFile(outputDirHandle, relFilePath, content);
    },
    async finish(logJsonString) {
      if (logJsonString) {
        await fsWriteFile(outputDirHandle, "_conversion_log.json", logJsonString);
      }
    },
    download() {
      // Direct file writes, no zip download needed
    },
  };
}

/**
 * Fetch supported formats allow-list from server using relative path for ROOT_PATH support.
 */
async function loadFormats() {
  try {
    const res = await fetch("api/formats", { credentials: "include" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} ${res.statusText}`);
    }
    state.formats = await res.json();
    if (el.errorBanner) {
      el.errorBanner.style.display = "none";
    }
  } catch (err) {
    console.error("Failed to load supported formats:", err);
    if (el.errorBanner) {
      el.errorBanner.textContent = `Error: Failed to load supported formats from server (${err.message}). Conversions may not work properly.`;
      el.errorBanner.style.display = "block";
    }
  }
}

/**
 * Update UI plan table from state.scannedItems using DOM methods to prevent XSS.
 */
function renderPlanTable() {
  el.planTitle.textContent = `Conversion Plan (${state.scannedItems.length} files)`;

  if (state.scannedItems.length === 0) {
    el.planTbody.innerHTML = `
      <tr>
        <td colspan="3" style="text-align: center; color: var(--text-muted);">
          No files found in selected folder.
        </td>
      </tr>
    `;
    el.btnConvert.disabled = true;
    return;
  }

  el.planTbody.textContent = "";
  state.scannedItems.forEach((item, index) => {
    const tr = document.createElement("tr");
    tr.id = `row-${index}`;

    const tdPath = document.createElement("td");
    tdPath.className = "col-path";
    tdPath.title = item.relPath;
    tdPath.textContent = item.relPath;

    const tdSize = document.createElement("td");
    tdSize.className = "col-size";
    tdSize.textContent = formatBytes(item.file.size);

    const tdStatus = document.createElement("td");
    tdStatus.id = `status-${index}`;

    let badgeClass = "badge-skipped";
    if (item.planStatus === "supported") {
      badgeClass = "badge-supported";
    }
    setStatus(tdStatus, badgeClass, item.planStatus);

    tr.appendChild(tdPath);
    tr.appendChild(tdSize);
    tr.appendChild(tdStatus);
    el.planTbody.appendChild(tr);
  });

  const hasSupported = state.scannedItems.some((i) => i.planStatus === "supported");
  const canConvert =
    hasSupported &&
    !state.isConverting &&
    (state.mode === "zip" || state.outputDirHandle !== null);

  el.btnConvert.disabled = !canConvert;
}

/**
 * Filter, classify, and resolve output names from raw scanned files.
 */
function processScannedFiles() {
  const recurse = el.optRecurse.checked;
  const filtered = filterByRecurse(state.rawScannedFiles, recurse);

  const classified = filtered.map((item) => ({
    ...item,
    planStatus: classifyFile(item.relPath, state.formats),
  }));

  // Resolve output names ONLY over supported files
  const supportedRelPaths = classified
    .filter((item) => item.planStatus === "supported")
    .map((item) => item.relPath);

  const resolvedOutputs = resolveOutputNames(supportedRelPaths);

  state.scannedItems = classified.map((item) => ({
    relPath: item.relPath,
    file: item.file,
    handle: item.handle,
    planStatus: item.planStatus,
    targetRelPath: resolvedOutputs[item.relPath] || `${item.relPath}.md`,
  }));

  renderPlanTable();
}

/**
 * Scan input directory using File System Access API.
 */
async function scanInputFolderFs() {
  if (!state.inputDirHandle) return;

  el.btnPickInput.disabled = true;
  el.planTbody.innerHTML = `
    <tr>
      <td colspan="3" style="text-align: center; color: var(--text-muted);">
        Scanning directory...
      </td>
    </tr>
  `;

  try {
    // Always collect recursively; filterByRecurse handles the option
    state.rawScannedFiles = await collectFiles(state.inputDirHandle, true);
    processScannedFiles();
  } catch (err) {
    console.error("Failed to scan directory:", err);
    alert(`Could not scan directory: ${err.message}`);
  } finally {
    el.btnPickInput.disabled = false;
  }
}

/**
 * Process a FileList from <input type=file webkitdirectory> or Drag & Drop.
 */
function handleFileList(fileList, folderName = "") {
  const files = Array.from(fileList);
  if (files.length === 0) return;

  const displayName =
    folderName ||
    (files[0].webkitRelativePath ? files[0].webkitRelativePath.split("/")[0] : `${files.length} files`);
  el.inputFolderName.textContent = `📁 ${displayName}`;

  state.rawScannedFiles = files.map((file) => {
    const rawPath = file.webkitRelativePath || file.name;
    const relPath = file.webkitRelativePath ? stripRootFolder(rawPath) : file.name;
    return {
      relPath,
      file,
      handle: null,
    };
  });

  processScannedFiles();
}

/**
 * Handle pick input folder button click.
 */
async function onPickInput() {
  if (state.mode === "zip") {
    el.inputFolderFile.click();
    return;
  }

  try {
    state.inputDirHandle = await pickDirectory();
    el.inputFolderName.textContent = `📁 ${state.inputDirHandle.name}`;
    el.btnPickOutput.disabled = false;
    await scanInputFolderFs();
  } catch (err) {
    if (err.name !== "AbortError") {
      console.error(err);
    }
  }
}

/**
 * Handle pick output folder button click (FS mode only).
 */
async function onPickOutput() {
  try {
    const handle = await pickDirectory();
    // Request readwrite permission once up front
    const permitted = await verifyReadWritePermission(handle);
    if (!permitted) {
      alert("Read/write permission is required to write converted files.");
      return;
    }

    state.outputDirHandle = handle;
    el.outputFolderName.textContent = `📂 ${state.outputDirHandle.name}`;

    const hasSupported = state.scannedItems.some((i) => i.planStatus === "supported");
    el.btnConvert.disabled = !hasSupported || state.isConverting;
  } catch (err) {
    if (err.name !== "AbortError") {
      console.error(err);
    }
  }
}

/**
 * POST api/convert with credentials: "include" and retry once on network error or 5xx.
 */
async function convertFileWithRetry(file, frontmatter) {
  const url = `api/convert?frontmatter=${frontmatter}&format=json`;
  let attempts = 0;

  while (attempts < 2) {
    attempts++;
    try {
      const fd = new FormData();
      fd.append("file", file);

      const res = await fetch(url, {
        method: "POST",
        credentials: "include",
        body: fd,
      });

      if (res.ok) {
        const data = await res.json();
        return { ok: true, data };
      }

      // 4xx: Never retry
      if (res.status >= 400 && res.status < 500) {
        let detail = `Error ${res.status}`;
        try {
          const errData = await res.json();
          if (errData.detail) detail = errData.detail;
        } catch {
          // ignore
        }
        return { ok: false, error: detail, status: res.status };
      }

      // 5xx: retry once if first attempt
      if (attempts === 1) {
        continue;
      }

      let detail = `Server error ${res.status}`;
      try {
        const errData = await res.json();
        if (errData.detail) detail = errData.detail;
      } catch {
        // ignore
      }
      return { ok: false, error: detail, status: res.status };
    } catch (netErr) {
      // Network error: retry once
      if (attempts === 1) {
        continue;
      }
      return { ok: false, error: netErr.message || "Network error" };
    }
  }
}

/**
 * Run conversion across the plan with pluggable output sink and concurrency 2.
 */
async function runConversion() {
  if (state.isConverting) return;
  if (state.mode === "fs" && !state.outputDirHandle) return;

  state.isConverting = true;
  el.btnConvert.disabled = true;
  el.btnPickInput.disabled = true;
  if (el.btnPickOutput) el.btnPickOutput.disabled = true;
  el.summaryCard.style.display = "none";
  el.singleCopyArea.style.display = "none";

  // Initialize output sink
  let sink;
  try {
    if (state.mode === "zip") {
      sink = await createZipSink();
    } else {
      sink = createFsSink(state.outputDirHandle);
    }
  } catch (sinkErr) {
    alert(`Could not initialize output sink: ${sinkErr.message}`);
    state.isConverting = false;
    el.btnConvert.disabled = false;
    el.btnPickInput.disabled = false;
    if (el.btnPickOutput) el.btnPickOutput.disabled = false;
    return;
  }

  const total = state.scannedItems.length;
  let processed = 0;
  let convertedCount = 0;
  let skippedCount = 0;
  let failedCount = 0;
  let lastConvertedMarkdown = null;
  let converterVersion = "unknown";

  const conversionLog = [];
  const startTime = Date.now();

  el.progressContainer.style.display = "block";
  el.progressText.style.display = "block";
  el.progressBar.style.width = "0%";
  el.progressText.textContent = `0 / ${total} files processed`;

  const skipUnchanged = state.mode === "fs" && el.optSkipUnchanged.checked;
  const frontmatter = el.optFrontmatter.checked;

  function updateProgress() {
    processed++;
    const pct = Math.round((processed / total) * 100);
    el.progressBar.style.width = `${pct}%`;
    el.progressText.textContent = `${processed} / ${total} files processed`;
  }

  // Queue runner with client concurrency 2
  let queueIndex = 0;
  async function worker() {
    while (queueIndex < state.scannedItems.length) {
      const idx = queueIndex++;
      const item = state.scannedItems[idx];
      const statusCell = document.getElementById(`status-${idx}`);
      const itemStart = Date.now();

      // Non-supported items are skipped immediately
      if (item.planStatus !== "supported") {
        skippedCount++;
        conversionLog.push({
          source: item.relPath,
          target: null,
          status: "skipped",
          error: item.planStatus,
          bytes: item.file.size,
          duration_ms: Date.now() - itemStart,
        });
        updateProgress();
        continue;
      }

      // Check skip unchanged (FS mode only)
      if (skipUnchanged) {
        const targetMtime = await getTargetLastModified(state.outputDirHandle, item.targetRelPath);
        if (shouldSkipUnchanged(item.file.lastModified, targetMtime)) {
          skippedCount++;
          setStatus(statusCell, "badge-skipped", "skipped (unchanged)");
          conversionLog.push({
            source: item.relPath,
            target: item.targetRelPath,
            status: "skipped",
            error: "unchanged",
            bytes: item.file.size,
            duration_ms: Date.now() - itemStart,
          });
          updateProgress();
          continue;
        }
      }

      // Convert file
      setStatus(statusCell, "badge-supported", "converting...");

      const result = await convertFileWithRetry(item.file, frontmatter);
      const durationMs = Date.now() - itemStart;

      if (result.ok) {
        try {
          await sink.writeFile(item.targetRelPath, result.data.markdown);
          convertedCount++;
          lastConvertedMarkdown = result.data.markdown;
          if (result.data.converter_version) {
            converterVersion = result.data.converter_version;
          }

          setStatus(statusCell, "badge-done", "done");
          conversionLog.push({
            source: item.relPath,
            target: item.targetRelPath,
            status: "done",
            error: null,
            bytes: item.file.size,
            duration_ms: durationMs,
          });
        } catch (writeErr) {
          failedCount++;
          setStatus(
            statusCell,
            "badge-failed",
            "failed: write error",
            `Write error: ${writeErr.message}`
          );
          conversionLog.push({
            source: item.relPath,
            target: item.targetRelPath,
            status: "failed",
            error: `Write error: ${writeErr.message}`,
            bytes: item.file.size,
            duration_ms: durationMs,
          });
        }
      } else {
        failedCount++;
        const reason = result.error || "conversion failed";
        setStatus(statusCell, "badge-failed", `failed: ${reason}`, reason);
        conversionLog.push({
          source: item.relPath,
          target: item.targetRelPath,
          status: "failed",
          error: reason,
          bytes: item.file.size,
          duration_ms: durationMs,
        });
      }

      updateProgress();
    }
  }

  // Run with concurrency 2
  await Promise.all([worker(), worker()]);

  // Finish output sink & generate log
  try {
    const logPayload = {
      started_at: new Date(startTime).toISOString(),
      finished_at: new Date().toISOString(),
      converter_version: converterVersion,
      summary: {
        converted: convertedCount,
        skipped: skippedCount,
        failed: failedCount,
        total,
      },
      files: conversionLog,
    };
    const logJson = JSON.stringify(logPayload, null, 2);
    const sinkResult = await sink.finish(logJson);

    if (sink.type === "zip" && sinkResult) {
      const zipName = generateZipFilename();
      sink.download(sinkResult, zipName);
    }
  } catch (logErr) {
    console.error("Failed to finish sink or write conversion log:", logErr);
  }

  // Display summary
  el.statConverted.textContent = convertedCount;
  el.statSkipped.textContent = skippedCount;
  el.statFailed.textContent = failedCount;
  el.summaryCard.style.display = "block";

  if (convertedCount === 1 && lastConvertedMarkdown) {
    state.convertedMarkdownSingle = lastConvertedMarkdown;
    el.singleCopyArea.style.display = "block";
  }

  state.isConverting = false;
  el.btnConvert.disabled = false;
  el.btnPickInput.disabled = false;
  if (el.btnPickOutput) el.btnPickOutput.disabled = false;
}

/**
 * Copy single file markdown to clipboard.
 */
async function onCopyMarkdown() {
  if (!state.convertedMarkdownSingle) return;
  try {
    await navigator.clipboard.writeText(state.convertedMarkdownSingle);
    el.copyStatus.style.display = "inline";
    setTimeout(() => {
      el.copyStatus.style.display = "none";
    }, 2000);
  } catch (err) {
    console.error("Clipboard copy failed:", err);
  }
}

/**
 * Initialize drag-and-drop listener on pickerCard.
 */
function initDragAndDrop() {
  const zone = el.pickerCard || document.body;

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    zone.style.outline = "2px dashed var(--primary)";
  });

  zone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    e.stopPropagation();
    zone.style.outline = "";
  });

  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    zone.style.outline = "";
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileList(e.dataTransfer.files, "Dropped files");
    }
  });
}

/**
 * Initialize application on page load.
 */
async function init() {
  // Feature detect File System Access API
  if (!isFileSystemAccessSupported()) {
    state.mode = "zip";
    el.fallbackNotice.style.display = "block";

    // Hide output-folder picker
    if (el.outputPickerContainer) {
      el.outputPickerContainer.style.display = "none";
    }

    // Disable skip-unchanged option in ZIP mode
    el.optSkipUnchanged.checked = false;
    el.optSkipUnchanged.disabled = true;
    el.optSkipUnchanged.parentElement.title =
      "Skip unchanged is not available in ZIP mode (no local destination folder to compare).";

    // Preload JSZip
    loadJSZip().catch((e) => console.warn("Failed preloading JSZip:", e));
  }

  // Load formats
  await loadFormats();

  // Event listeners
  el.btnPickInput.addEventListener("click", onPickInput);
  if (el.btnPickOutput) {
    el.btnPickOutput.addEventListener("click", onPickOutput);
  }

  el.inputFolderFile.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileList(e.target.files);
    }
  });

  el.btnConvert.addEventListener("click", runConversion);
  el.btnCopyMarkdown.addEventListener("click", onCopyMarkdown);

  el.optRecurse.addEventListener("change", () => {
    if (state.rawScannedFiles.length > 0) {
      processScannedFiles();
    }
  });

  initDragAndDrop();
}

window.addEventListener("DOMContentLoaded", init);
