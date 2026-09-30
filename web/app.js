const state = {
  videoId: null,
  metadata: null,
  image: null,
  selection: null,
  drawing: false,
  start: null,
  pollingTimer: null,
};

const uploadView = document.querySelector("#upload-view");
const selectView = document.querySelector("#select-view");
const runView = document.querySelector("#run-view");
const dropZone = document.querySelector("#drop-zone");
const videoInput = document.querySelector("#video-input");
const uploadStatus = document.querySelector("#upload-status");
const fileName = document.querySelector("#file-name");
const fileMeta = document.querySelector("#file-meta");
const canvas = document.querySelector("#roi-canvas");
const context = canvas.getContext("2d");
const selectionCopy = document.querySelector("#selection-copy");
const clearButton = document.querySelector("#clear-button");
const replaceButton = document.querySelector("#replace-button");
const runButton = document.querySelector("#run-button");
const progressOrbit = document.querySelector("#progress-orbit");
const runKicker = document.querySelector("#run-kicker");
const runTitle = document.querySelector("#run-title");
const runMessage = document.querySelector("#run-message");
const progressFill = document.querySelector("#progress-fill");
const progressLabel = document.querySelector("#progress-label");
const resultPreview = document.querySelector("#result-preview");
const resultImage = document.querySelector("#result-image");
const resultActions = document.querySelector("#result-actions");
const downloadButton = document.querySelector("#download-button");
const anotherButton = document.querySelector("#another-button");
const steps = [...document.querySelectorAll(".step")];

function apiError(payload, fallback) {
  return payload?.detail || payload?.message || fallback;
}

function setStep(name) {
  const order = ["upload", "select", "run"];
  const activeIndex = order.indexOf(name);
  steps.forEach((step, index) => {
    step.classList.toggle("is-active", index <= activeIndex);
  });
}

function showView(name) {
  uploadView.hidden = name !== "upload";
  selectView.hidden = name !== "select";
  runView.hidden = name !== "run";
  setStep(name);
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return minutes ? `${minutes}m ${remainder.toFixed(1)}s` : `${remainder.toFixed(1)}s`;
}

async function parseResponse(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // Use the fallback below.
  }
  if (!response.ok) throw new Error(apiError(payload, `Request failed (${response.status})`));
  return payload;
}

async function uploadFile(file) {
  if (!file) return;
  uploadStatus.classList.remove("is-error");
  uploadStatus.textContent = `Uploading ${file.name}…`;
  dropZone.classList.add("is-busy");
  const body = new FormData();
  body.append("file", file);

  try {
    const response = await fetch("/api/videos", { method: "POST", body });
    const metadata = await parseResponse(response);
    state.videoId = metadata.video_id;
    state.metadata = metadata;
    state.selection = null;
    await loadPreview(metadata.preview_url);
    fileName.textContent = metadata.filename;
    fileMeta.textContent = `${metadata.width} × ${metadata.height} · ${metadata.frame_count} frames · ${metadata.fps.toFixed(2)} fps · ${formatDuration(metadata.duration_seconds)} · ${formatBytes(metadata.size_bytes)}`;
    clearSelection();
    showView("select");
  } catch (error) {
    uploadStatus.classList.add("is-error");
    uploadStatus.textContent = error.message;
  } finally {
    dropZone.classList.remove("is-busy");
    videoInput.value = "";
  }
}

function loadPreview(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      state.image = image;
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      drawCanvas();
      resolve();
    };
    image.onerror = () => reject(new Error("The first-frame preview could not be loaded."));
    image.src = `${url}?t=${Date.now()}`;
  });
}

function drawCanvas() {
  if (!state.image) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(state.image, 0, 0, canvas.width, canvas.height);
  const selection = normalizedSelection();
  if (!selection) return;

  context.fillStyle = "rgba(0, 0, 0, 0.35)";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(
    state.image,
    selection.x,
    selection.y,
    selection.width,
    selection.height,
    selection.x,
    selection.y,
    selection.width,
    selection.height,
  );
  const cssScale = canvas.getBoundingClientRect().width / canvas.width || 1;
  context.strokeStyle = "#bdf4cc";
  context.lineWidth = 3 / cssScale;
  context.strokeRect(selection.x, selection.y, selection.width, selection.height);
}

function canvasPoint(event) {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(canvas.width, ((event.clientX - bounds.left) / bounds.width) * canvas.width)),
    y: Math.max(0, Math.min(canvas.height, ((event.clientY - bounds.top) / bounds.height) * canvas.height)),
  };
}

function normalizedSelection() {
  if (!state.selection) return null;
  const { x1, y1, x2, y2 } = state.selection;
  return {
    x: Math.round(Math.min(x1, x2)),
    y: Math.round(Math.min(y1, y2)),
    width: Math.round(Math.abs(x2 - x1)),
    height: Math.round(Math.abs(y2 - y1)),
  };
}

function updateSelectionUI() {
  const selection = normalizedSelection();
  const valid = selection && selection.width >= 3 && selection.height >= 3;
  runButton.disabled = !valid;
  clearButton.disabled = !selection;
  selectionCopy.textContent = valid
    ? `Selected ${selection.width} × ${selection.height} px at (${selection.x}, ${selection.y}). Drag again to replace it.`
    : "Drag tightly around a distinctive feature attached to the moving actuator.";
}

function clearSelection() {
  state.selection = null;
  drawCanvas();
  updateSelectionUI();
}

canvas.addEventListener("pointerdown", (event) => {
  if (!state.image) return;
  canvas.setPointerCapture(event.pointerId);
  state.drawing = true;
  state.start = canvasPoint(event);
  state.selection = { x1: state.start.x, y1: state.start.y, x2: state.start.x, y2: state.start.y };
  drawCanvas();
});

canvas.addEventListener("pointermove", (event) => {
  if (!state.drawing || !state.selection) return;
  const point = canvasPoint(event);
  state.selection.x2 = point.x;
  state.selection.y2 = point.y;
  drawCanvas();
});

function finishDrawing(event) {
  if (!state.drawing) return;
  state.drawing = false;
  if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  updateSelectionUI();
}

canvas.addEventListener("pointerup", finishDrawing);
canvas.addEventListener("pointercancel", finishDrawing);

async function startTracking() {
  const selection = normalizedSelection();
  if (!selection || runButton.disabled) return;
  showView("run");
  setRunningState();
  try {
    const response = await fetch(`/api/videos/${state.videoId}/track`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(selection),
    });
    const job = await parseResponse(response);
    pollJob(job.job_id);
  } catch (error) {
    showError(error.message);
  }
}

function setRunningState() {
  progressOrbit.classList.remove("is-complete");
  runKicker.textContent = "Tracking in progress";
  runTitle.textContent = "Following your selection.";
  runMessage.textContent = "Preparing the video…";
  progressFill.style.width = "0%";
  progressLabel.textContent = "0%";
  resultPreview.hidden = true;
  resultImage.removeAttribute("src");
  resultActions.hidden = true;
}

async function pollJob(jobId) {
  window.clearTimeout(state.pollingTimer);
  try {
    const response = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
    const job = await parseResponse(response);
    const progress = Number(job.progress || 0);
    progressFill.style.width = `${progress}%`;
    progressLabel.textContent = `${progress}%`;
    runMessage.textContent = job.message || "Processing…";

    if (job.status === "complete") {
      showComplete(job);
      return;
    }
    if (job.status === "error") {
      showError(job.error || job.message || "Tracking failed.");
      return;
    }
    state.pollingTimer = window.setTimeout(() => pollJob(jobId), 700);
  } catch (error) {
    showError(error.message);
  }
}

function showComplete(job) {
  progressOrbit.classList.add("is-complete");
  runKicker.textContent = "Tracking complete";
  runTitle.textContent = "Your results are ready.";
  runMessage.textContent = `${job.successful_frames} frames tracked · ${job.failed_frames} failures`;
  progressFill.style.width = "100%";
  progressLabel.textContent = "100%";
  resultImage.src = `${job.plot_url}?t=${Date.now()}`;
  resultPreview.hidden = false;
  downloadButton.href = job.download_url;
  resultActions.hidden = false;
}

function showError(message) {
  progressOrbit.classList.remove("is-complete");
  runKicker.textContent = "Unable to complete";
  runTitle.textContent = "Something went wrong.";
  runMessage.textContent = message;
  progressFill.style.width = "0%";
  progressLabel.textContent = "";
  resultPreview.hidden = true;
  resultImage.removeAttribute("src");
  downloadButton.hidden = true;
  resultActions.hidden = false;
}

function resetApp() {
  window.clearTimeout(state.pollingTimer);
  Object.assign(state, {
    videoId: null,
    metadata: null,
    image: null,
    selection: null,
    drawing: false,
    start: null,
    pollingTimer: null,
  });
  uploadStatus.textContent = "";
  uploadStatus.classList.remove("is-error");
  downloadButton.hidden = false;
  resultPreview.hidden = true;
  resultImage.removeAttribute("src");
  resultActions.hidden = true;
  context.clearRect(0, 0, canvas.width, canvas.height);
  showView("upload");
}

videoInput.addEventListener("change", () => uploadFile(videoInput.files[0]));
dropZone.addEventListener("dragenter", (event) => {
  event.preventDefault();
  dropZone.classList.add("is-dragging");
});
dropZone.addEventListener("dragover", (event) => event.preventDefault());
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("is-dragging"));
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("is-dragging");
  uploadFile(event.dataTransfer.files[0]);
});
clearButton.addEventListener("click", clearSelection);
replaceButton.addEventListener("click", resetApp);
anotherButton.addEventListener("click", resetApp);
runButton.addEventListener("click", startTracking);

showView("upload");
