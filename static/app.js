const STATUS_LABELS = {
  queued: "En cola",
  running: "Descargando",
  done: "Completado",
  error: "Error",
  cancelled: "Cancelado",
};

const RESULT_LABELS = {
  pending: "Pendiente",
  running: "En curso",
  done: "Listo",
  error: "Error",
  cancelled: "Cancelado",
};

const form = document.getElementById("download-form");
const submitBtn = document.getElementById("submit-btn");
const urlsInput = document.getElementById("urls");
const qualitySelect = document.getElementById("quality");
const audioFormatSelect = document.getElementById("audio_format");
const langsInput = document.getElementById("langs");
const playlistInput = document.getElementById("playlist");
const formError = document.getElementById("form-error");

const jobPanel = document.getElementById("job-panel");
const jobStatus = document.getElementById("job-status");
const jobMessage = document.getElementById("job-message");
const progressBar = document.getElementById("progress-bar");
const progressPercent = document.getElementById("progress-percent");
const progressSpeed = document.getElementById("progress-speed");
const progressEta = document.getElementById("progress-eta");
const jobResults = document.getElementById("job-results");
const cancelBtn = document.getElementById("cancel-btn");

const fileList = document.getElementById("file-list");
const emptyFiles = document.getElementById("empty-files");
const refreshFilesBtn = document.getElementById("refresh-files");

let activeJobId = null;
let pollTimer = null;

const URL_RE = /https?:\/\/[^\s<>"']+/g;

function trimUrl(value) {
  let url = value;
  let suffix = "";
  while (/[.,;:!?]$/.test(url)) {
    suffix = url.slice(-1) + suffix;
    url = url.slice(0, -1);
  }
  const opens = (url.match(/\(/g) || []).length;
  const closes = (url.match(/\)/g) || []).length;
  if (closes > opens && url.endsWith(")")) {
    suffix = ")" + suffix;
    url = url.slice(0, -1);
  }
  return { url, suffix };
}

function linkify(text) {
  const fragment = document.createDocumentFragment();
  const value = String(text ?? "");
  let lastIndex = 0;

  for (const match of value.matchAll(URL_RE)) {
    const index = match.index ?? 0;
    fragment.append(document.createTextNode(value.slice(lastIndex, index)));

    const { url, suffix } = trimUrl(match[0]);
    const link = document.createElement("a");
    link.href = url;
    link.textContent = url;
    link.className = "message-link";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    fragment.append(link);

    if (suffix) {
      fragment.append(document.createTextNode(suffix));
    }
    lastIndex = index + match[0].length;
  }

  fragment.append(document.createTextNode(value.slice(lastIndex)));
  return fragment;
}

function setLinkified(element, text) {
  element.replaceChildren(linkify(text));
}

function showFormError(message) {
  setLinkified(formError, message);
  formError.hidden = false;
}

function clearFormError() {
  formError.hidden = true;
  formError.replaceChildren();
}

document.querySelectorAll('input[name="mode"]').forEach((radio) => {
  radio.addEventListener("change", updateModeFields);
});
updateModeFields();

function currentMode() {
  const selected = document.querySelector('input[name="mode"]:checked');
  return selected ? selected.value : "video";
}

function updateModeFields() {
  const mode = currentMode();
  document.getElementById("quality-wrap").hidden = mode !== "video";
  document.getElementById("audio-format-wrap").hidden = mode !== "audio";
  document.getElementById("langs-wrap").hidden = mode !== "txt";
}

function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, exponent);
  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function resetSubmit() {
  submitBtn.disabled = false;
  submitBtn.textContent = "Descargar";
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollJob, 900);
  pollJob();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    urls: urlsInput.value,
    mode: currentMode(),
    quality: qualitySelect.value,
    audio_format: audioFormatSelect.value,
    langs: langsInput.value,
    playlist: playlistInput.checked,
  };

  submitBtn.disabled = true;
  submitBtn.textContent = "Iniciando...";
  clearFormError();

  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "No se pudo iniciar la descarga.");
    }
    activeJobId = data.id;
    cancelBtn.disabled = false;
    showJob(data.job);
    startPolling();
  } catch (error) {
    showFormError(error.message);
    resetSubmit();
  }
});

async function pollJob() {
  if (!activeJobId) return;
  try {
    const response = await fetch(`/api/jobs/${activeJobId}`);
    if (!response.ok) {
      throw new Error("No se encontró la descarga.");
    }
    const job = await response.json();
    showJob(job);
    if (["done", "error", "cancelled"].includes(job.status)) {
      stopPolling();
      resetSubmit();
      loadFiles();
    }
  } catch (error) {
    stopPolling();
    resetSubmit();
    setLinkified(jobMessage, error.message);
  }
}

cancelBtn.addEventListener("click", async () => {
  if (!activeJobId) return;
  cancelBtn.disabled = true;
  try {
    await fetch(`/api/jobs/${activeJobId}/cancel`, { method: "POST" });
  } catch (error) {
    console.error(error);
    cancelBtn.disabled = false;
  }
});

function showJob(job) {
  jobPanel.hidden = false;
  jobPanel.dataset.status = job.status;

  jobStatus.textContent = STATUS_LABELS[job.status] || job.status;
  jobStatus.className = `status status-${job.status}`;
  setLinkified(jobMessage, job.message || "");

  const percent = Math.min(100, Math.max(0, Number(job.progress && job.progress.percent) || 0));
  progressBar.style.width = `${percent}%`;
  progressPercent.textContent = `${percent.toFixed(percent > 0 && percent < 10 ? 1 : 0)}%`;

  const speed = job.progress && job.progress.speed;
  progressSpeed.textContent = speed ? `${formatSize(speed)}/s` : "";

  const eta = job.progress && job.progress.eta;
  progressEta.textContent = Number.isFinite(eta) && eta > 0 ? `quedan ${formatDuration(eta)}` : "";

  cancelBtn.hidden = ["done", "error", "cancelled"].includes(job.status);

  jobResults.replaceChildren();
  for (const result of job.results || []) {
    const item = document.createElement("li");

    const row = document.createElement("div");
    row.className = "result-row";

    const url = document.createElement("span");
    url.className = "result-url";
    url.textContent = result.url;

    const status = document.createElement("span");
    status.className = `result-status result-${result.status}`;
    status.textContent = RESULT_LABELS[result.status] || result.status;

    row.append(url, status);
    item.append(row);

    if (result.error) {
      const error = document.createElement("p");
      error.className = "result-error-message";
      setLinkified(error, result.error);
      item.append(error);
    }

    for (const name of result.files || []) {
      const link = document.createElement("a");
      link.className = "result-file";
      link.href = `/files/${encodeURIComponent(name)}`;
      link.textContent = name;
      item.append(link);
    }

    jobResults.append(item);
  }
}

async function loadFiles() {
  try {
    const response = await fetch("/api/files");
    const data = await response.json();
    fileList.replaceChildren();
    emptyFiles.hidden = data.files.length > 0;

    for (const file of data.files) {
      const item = document.createElement("li");

      const info = document.createElement("div");
      info.className = "file-info";

      const link = document.createElement("a");
      link.href = file.url;
      link.textContent = file.name;

      const meta = document.createElement("span");
      meta.textContent = `${formatSize(file.size)} · ${new Date(file.mtime * 1000).toLocaleString()}`;

      info.append(link, meta);

      const actions = document.createElement("div");
      actions.className = "file-actions";

      const download = document.createElement("a");
      download.href = file.url;
      download.className = "ghost small";
      download.textContent = "Descargar";
      download.setAttribute("download", "");

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ghost small danger";
      remove.textContent = "Eliminar";
      remove.addEventListener("click", () => deleteFile(file.name));

      actions.append(download, remove);
      item.append(info, actions);
      fileList.append(item);
    }
  } catch (error) {
    console.error(error);
  }
}

async function deleteFile(name) {
  if (!confirm(`¿Eliminar "${name}"?`)) return;
  try {
    const response = await fetch(`/api/files/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || "No se pudo eliminar el archivo.");
    }
    await loadFiles();
  } catch (error) {
    alert(error.message);
  }
}

refreshFilesBtn.addEventListener("click", loadFiles);
loadFiles();
