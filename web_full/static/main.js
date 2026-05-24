/* global Editor, Preview, CanvasViz */
/**
 * main.js  (Architecture B — full server-side pipeline)
 *
 * Differences from the Pyodide version:
 *   - No in-browser Python; all trajectory/compositor work happens on the server.
 *   - Scene data, depth overlay, and sprites are fetched as regular HTTP resources.
 *   - generate / optimize POST to /api/generate and /api/optimize.
 *   - Composite POSTs to /api/composite (async job) and polls /api/job/<id>.
 *   - Save operations download pre-built server files via /api/download/.
 *
 * Views (tabs):
 *   depth      → editor canvas + depth overlay
 *   trajectory → editor canvas + draggable waypoints
 *   compare    → side-by-side canvas-viz panels
 *   composite  → compositor settings, run button, download link
 *   preview    → editor canvas + animated sprite (live, not the rendered video)
 */

// ── Global app state ──────────────────────────────────────────────
let sceneData  = null;   // response from /api/scene
let bgImage    = null;   // HTMLImageElement (background)
let autoResult = null;   // {keypoints, floor_profile, fps}
let optResult  = null;   // {keypoints, intersections, strategy_colours}

let currentView = "depth";
let prevView    = "trajectory";

let _compositePollTimer = null;   // setInterval handle for compositor polling

// ── Status helper ─────────────────────────────────────────────────
function setStatus(msg, cls = "status-loading") {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.className   = cls;
}

// ── View management ───────────────────────────────────────────────
function setView(view) {
  currentView = view;

  const showCanvas    = view !== "compare" && view !== "composite";
  const showCompare   = view === "compare";
  const showComposite = view === "composite";

  document.getElementById("canvas-wrap").style.display      = showCanvas    ? "" : "none";
  document.getElementById("comparison").style.display        = showCompare   ? "flex" : "none";
  document.getElementById("composite-panel").style.display   = showComposite ? "flex" : "none";

  ["depth", "trajectory", "compare", "composite", "preview"].forEach(v => {
    document.getElementById(`tab-${v}`).classList.toggle("active", v === view);
  });

  if (view === "depth") {
    const cb = document.getElementById("show-depth");
    if (cb && !cb.checked) { cb.checked = true; if (Editor.redraw) Editor.redraw(); }
  }

  updateButtonStates();
}

function updateButtonStates() {
  const ready   = !!bgImage;
  const hasAuto = !!autoResult;
  const hasOpt  = !!optResult;

  document.getElementById("btn-generate").disabled = !ready;
  document.getElementById("btn-optimize").disabled = !hasAuto;
  document.getElementById("btn-play").disabled     = !hasAuto;
  document.getElementById("btn-clear").disabled    = !hasAuto;
  document.getElementById("btn-save").disabled     = !hasAuto;
  document.getElementById("btn-composite").disabled = !hasAuto;

  document.getElementById("tab-depth").disabled      = !ready;
  document.getElementById("tab-trajectory").disabled = !hasAuto;
  document.getElementById("tab-compare").disabled    = !hasOpt;
  document.getElementById("tab-composite").disabled  = !hasAuto;
  document.getElementById("tab-preview").disabled    = !hasAuto;

  const saveStepEl = document.getElementById("btn-save-step");
  const labels = {
    depth:      "Save Depth PNG",
    trajectory: "Save Auto Trajectory",
    compare:    "Save Optimized",
    composite:  "—",
    preview:    "—",
  };
  saveStepEl.textContent = labels[currentView] || "Save View";
  saveStepEl.disabled = (
    ["composite", "preview"].includes(currentView) ||
    (currentView === "depth"      && !ready)   ||
    (currentView === "trajectory" && !hasAuto) ||
    (currentView === "compare"    && !hasOpt)
  );
}

function disableButtons(on) {
  if (on) {
    document.querySelectorAll("#toolbar button, #view-tabs button")
      .forEach(b => { b.disabled = true; });
    document.getElementById("btn-composite").disabled = true;
  } else {
    updateButtonStates();
  }
}

// ── Load scene from server ────────────────────────────────────────
async function loadScene() {
  setStatus("Loading scene from server…");

  const resp = await fetch("/api/scene");
  if (!resp.ok) throw new Error("Server not ready. Start server.py first.");
  sceneData = await resp.json();

  // Load background image
  bgImage = await new Promise((resolve, reject) => {
    const img = new Image();
    img.onload  = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load background image"));
    img.src = sceneData.image_url;
  });

  // Load depth overlay PNG from server and convert to OffscreenCanvas
  setStatus("Loading depth overlay…");
  const depthImg = await new Promise((resolve, reject) => {
    const img = new Image();
    img.onload  = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load depth overlay"));
    img.src = sceneData.depth_overlay_url;
  });
  const depthOC  = new OffscreenCanvas(depthImg.naturalWidth, depthImg.naturalHeight);
  const depthCtx = depthOC.getContext("2d");
  depthCtx.drawImage(depthImg, 0, 0);
  Editor.setDepthImage(depthOC);

  // Load sprite GIFs
  if (sceneData.sprites && Object.keys(sceneData.sprites).length) {
    Preview.load(sceneData.sprites);
  }
}

// ── Keypoint sidebar ──────────────────────────────────────────────
function updateSidebar(kps) {
  const list = document.getElementById("keypoint-list");
  const cnt  = document.getElementById("kp-count");
  cnt.textContent = `(${kps.length})`;
  list.innerHTML  = "";
  kps.forEach((kp, i) => {
    const row     = document.createElement("div");
    row.className = "kp-row" + (i === Editor.selectedIndex ? " selected" : "");
    const pos     = `(${kp.foot_position[0]},${kp.foot_position[1]})`;
    row.innerHTML = `
      <span class="kp-idx">${i}</span>
      <span class="kp-pos">${pos}</span>
      <span class="kp-anim">${kp.animation}</span>`;
    row.addEventListener("click", () => {
      document.querySelectorAll(".kp-row").forEach(r => r.classList.remove("selected"));
      row.classList.add("selected");
    });
    list.appendChild(row);
  });
}

// ── Generate auto trajectory ──────────────────────────────────────
async function runGenerate() {
  setStatus("Running auto_trajectory on server…", "status-working");
  disableButtons(true);

  const frameSpacing = parseInt(document.getElementById("frame-spacing").value || "20");
  const params = {
    n_keypoints:   parseInt(document.getElementById("n-keypoints").value),
    frame_spacing: frameSpacing,
    fps:           sceneData.fps || 30,
    path_style:    document.getElementById("path-style").value,
    floor_y_frac:  0.45,
    max_depth_m:   2.0,
    start_y_frac:  0.90,
    end_y_frac:    0.55,
    seed:          42,
  };

  try {
    const resp = await fetch("/api/generate", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(params),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || "Generate failed");
    }
    autoResult = await resp.json();
    optResult  = null;

    Editor.loadKeypoints(autoResult.keypoints, frameSpacing);
    Editor.loadFloorProfile(autoResult.floor_profile || []);
    updateSidebar(autoResult.keypoints);

    // Pre-draw auto canvas for when user switches to Compare tab
    const autoCanvas = document.getElementById("auto-canvas");
    CanvasViz.draw(autoCanvas, bgImage, autoResult.keypoints, sceneData.objects, {
      floorProfile: autoResult.floor_profile || [],
      title: "Auto-generated",
    });
    _clearOptCanvas();

    setView("trajectory");
    setStatus("Auto path generated. Drag waypoints or run the Optimizer.", "status-ready");
  } catch (err) {
    setStatus("Error: " + err.message, "status-error");
    console.error(err);
  } finally {
    disableButtons(false);
  }
}

function _clearOptCanvas() {
  const oc  = document.getElementById("opt-canvas");
  const ctx = oc.getContext("2d");
  oc.width  = 400;
  oc.height = 300;
  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, 400, 300);
  ctx.fillStyle = "#555";
  ctx.font = "18px system-ui";
  ctx.fillText("Run Optimizer to see comparison", 20, 150);
}

// ── Run trajectory optimizer ──────────────────────────────────────
async function runOptimizer() {
  if (!autoResult) return;
  setStatus("Running optimizer on server…", "status-working");
  disableButtons(true);

  const currentKps = Editor.getKeypoints();
  const params = {
    keypoints:     currentKps,
    strategy:      document.getElementById("opt-strategy").value,
    depth_margin:  parseFloat(document.getElementById("depth-margin").value),
    around_margin: parseInt(document.getElementById("around-margin").value),
  };

  try {
    const resp = await fetch("/api/optimize", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(params),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || "Optimizer failed");
    }
    optResult = await resp.json();

    // Determine which frames are "inserted" (not in original)
    const origFrames  = new Set(currentKps.map(kp => kp.frame));
    const insertedSet = new Set(
      optResult.keypoints.filter(kp => !origFrames.has(kp.frame)).map(kp => kp.frame)
    );

    const autoCanvas = document.getElementById("auto-canvas");
    const optCanvas  = document.getElementById("opt-canvas");
    CanvasViz.draw(autoCanvas, bgImage, currentKps, sceneData.objects, {
      floorProfile: autoResult.floor_profile || [],
      title: "Auto-generated",
    });
    CanvasViz.draw(optCanvas, bgImage, optResult.keypoints, sceneData.objects, {
      intersections:   optResult.intersections,
      strategyColours: optResult.strategy_colours,
      insertedSet,
      title: "Optimized",
    });

    setView("compare");
    setStatus(
      `Optimized: ${optResult.keypoints.length} keypoints `
      + `(${optResult.keypoints.length - currentKps.length > 0 ? "+" : ""}${optResult.keypoints.length - currentKps.length} inserted). `
      + `${optResult.intersections.length} intersection(s) resolved.`,
      "status-ready"
    );
  } catch (err) {
    setStatus("Optimizer error: " + err.message, "status-error");
    console.error(err);
  } finally {
    disableButtons(false);
  }
}

// ── Run compositor (async) ────────────────────────────────────────
async function runComposite() {
  if (!autoResult) return;

  // Stop any previous poll
  if (_compositePollTimer) { clearInterval(_compositePollTimer); _compositePollTimer = null; }

  const kps = optResult ? optResult.keypoints : Editor.getKeypoints();
  const whichSelect = document.getElementById("composite-which");
  const useOpt      = whichSelect.value === "optimized" && !!optResult;

  const params = {
    keypoints:         useOpt ? optResult.keypoints : Editor.getKeypoints(),
    fps:               autoResult.fps || 30,
    global_scale:      parseFloat(document.getElementById("global-scale").value || "1.0"),
    depth_tolerance_m: parseFloat(document.getElementById("depth-tolerance").value || "0.0"),
  };

  const msgEl  = document.getElementById("composite-msg");
  const dlEl   = document.getElementById("composite-download");
  const btn    = document.getElementById("btn-composite");

  btn.disabled = true;
  dlEl.style.display = "none";
  msgEl.textContent  = "Starting compositor…";
  setStatus("Compositor starting…", "status-working");

  try {
    const resp = await fetch("/api/composite", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(params),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || "Composite failed to start");
    }
    const { job_id } = await resp.json();
    msgEl.textContent = "Compositor running…";

    // Poll every 2 seconds
    _compositePollTimer = setInterval(async () => {
      try {
        const jobResp = await fetch(`/api/job/${job_id}`);
        const job     = await jobResp.json();

        if (job.status === "done") {
          clearInterval(_compositePollTimer);
          _compositePollTimer = null;
          btn.disabled = false;

          const linkEl = document.getElementById("download-video");
          linkEl.href  = job.download_url;
          document.getElementById("composite-elapsed").textContent =
            `Rendered in ${job.elapsed_s}s`;
          dlEl.style.display = "flex";
          msgEl.textContent  = "Video ready:";
          setStatus(`Video composited in ${job.elapsed_s}s`, "status-ready");

        } else if (job.status === "error") {
          clearInterval(_compositePollTimer);
          _compositePollTimer = null;
          btn.disabled  = false;
          msgEl.textContent = "Error: " + job.error;
          setStatus("Compositor error: " + job.error, "status-error");

        } else {
          msgEl.textContent = `Compositor running… ${job.elapsed_s}s elapsed`;
          setStatus(`Compositing… ${job.elapsed_s}s`, "status-working");
        }
      } catch (pollErr) {
        console.error("Poll error:", pollErr);
      }
    }, 2000);

  } catch (err) {
    btn.disabled = false;
    msgEl.textContent = "Error: " + err.message;
    setStatus("Error: " + err.message, "status-error");
    console.error(err);
  }
}

// ── Save current view ─────────────────────────────────────────────
async function saveCurrentView() {
  if (currentView === "depth") {
    // Download the server-generated depth overlay
    _triggerDownload("/api/download/depth_overlay.png", "depth_overlay.png");

  } else if (currentView === "trajectory" && autoResult) {
    _triggerDownload("/api/download/auto_trajectory.json",   "auto_trajectory.json");
    _triggerDownload("/api/download/auto_trajectory.debug.png", "auto_trajectory.debug.png");
    setStatus("Downloading auto trajectory (2 files)…", "status-ready");

  } else if (currentView === "compare" && optResult) {
    _triggerDownload("/api/download/optimized_trajectory.json",   "optimized_trajectory.json");
    _triggerDownload("/api/download/optimized_trajectory.debug.png", "optimized_trajectory.debug.png");
    setStatus("Downloading optimized trajectory (2 files)…", "status-ready");
  }
}

// ── Save all ──────────────────────────────────────────────────────
async function saveAll() {
  if (!autoResult) { alert("Generate a trajectory first."); return; }
  _triggerDownload("/api/download/auto_trajectory.json",      "auto_trajectory.json");
  _triggerDownload("/api/download/auto_trajectory.debug.png", "auto_trajectory.debug.png");
  if (optResult) {
    _triggerDownload("/api/download/optimized_trajectory.json",      "optimized_trajectory.json");
    _triggerDownload("/api/download/optimized_trajectory.debug.png", "optimized_trajectory.debug.png");
  }
  const count = optResult ? "4 files" : "2 files (auto only)";
  setStatus(`Downloading ${count}…`, "status-ready");
}

function _triggerDownload(url, filename) {
  const a = document.createElement("a");
  a.href     = url;
  a.download = filename;
  a.click();
}

// ── Wire up all buttons ───────────────────────────────────────────
function bindButtons() {
  // Tab clicks
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      if (!tab.disabled) setView(tab.dataset.view);
    });
  });

  document.getElementById("btn-generate").addEventListener("click", runGenerate);
  document.getElementById("btn-optimize").addEventListener("click", runOptimizer);
  document.getElementById("btn-composite").addEventListener("click", () => {
    setView("composite");
    runComposite();
  });
  document.getElementById("btn-save-step").addEventListener("click", saveCurrentView);
  document.getElementById("btn-save").addEventListener("click", saveAll);

  document.getElementById("btn-clear").addEventListener("click", () => {
    if (Preview.isPlaying()) Preview.stop();
    if (_compositePollTimer) { clearInterval(_compositePollTimer); _compositePollTimer = null; }
    Editor.clear();
    autoResult = null;
    optResult  = null;
    updateSidebar([]);
    document.getElementById("btn-play").style.display = "";
    document.getElementById("btn-stop").style.display = "none";
    document.getElementById("composite-msg").textContent =
      "Run the compositor to generate the video.";
    document.getElementById("composite-download").style.display = "none";
    setView("depth");
  });

  // Play / Stop preview
  document.getElementById("btn-play").addEventListener("click", () => {
    const kps = optResult ? optResult.keypoints : (autoResult ? Editor.getKeypoints() : []);
    if (!kps.length) return;
    prevView = currentView;
    Preview.start(kps, autoResult?.fps || 30);
    setView("preview");
    document.getElementById("btn-play").style.display = "none";
    document.getElementById("btn-stop").style.display = "";
    document.getElementById("btn-stop").disabled = false;
  });

  document.getElementById("btn-stop").addEventListener("click", () => {
    Preview.stop();
    setView(prevView);
    document.getElementById("btn-stop").style.display = "none";
    document.getElementById("btn-play").style.display = "";
  });

  // Save individual comparison PNGs (inline canvas renderings)
  document.querySelectorAll(".btn-save-panel").forEach(btn => {
    btn.addEventListener("click", async () => {
      const which    = btn.dataset.which;
      const canvasId = which === "auto" ? "auto-canvas" : "opt-canvas";
      const filename = which === "auto"
        ? "auto_trajectory.debug.png"
        : "optimized_trajectory.debug.png";
      const blob = await new Promise(r =>
        document.getElementById(canvasId).toBlob(r, "image/png")
      );
      const url = URL.createObjectURL(blob);
      const a   = document.createElement("a");
      a.href     = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    });
  });

  // Editor callbacks
  Editor._onKeypointsChange = () => updateSidebar(Editor.getKeypoints());
}

// ── Entry point ───────────────────────────────────────────────────
(async () => {
  try {
    bindButtons();
    await loadScene();

    // Enable depth overlay before init so the first draw shows depth
    document.getElementById("show-depth").checked = true;

    Editor.init(document.getElementById("editor-canvas"), bgImage, sceneData);

    setView("depth");
    setStatus("Ready — depth overlay shown. Click Auto-Generate Path to begin.", "status-ready");
  } catch (err) {
    setStatus("Init failed: " + err.message, "status-error");
    console.error(err);
  }
})();
