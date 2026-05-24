/**
 * canvas_editor.js
 *
 * Interactive canvas for placing and dragging trajectory waypoints.
 *
 * Public API (used by main.js):
 *   Editor.init(canvasEl, bgImage, sceneData)
 *   Editor.loadKeypoints(keypoints)   – replace all waypoints (from Python)
 *   Editor.loadFloorProfile(profile)  – [[x, yMin, yMax], …] for overlay
 *   Editor.getKeypoints()             – return current waypoints as JSON-ready list
 *   Editor.clear()
 *   Editor.setDepthArray(flat, h, w)  – for depth readout on hover
 *   Editor.setDepthImage(imageData)   – RGBA ImageData of colourised depth
 *   Editor.selectedIndex              – currently selected waypoint index
 *
 * Overlay toggles are read from checkboxes #show-depth #show-floor #show-bboxes.
 */

const Editor = (() => {

  // ── State ─────────────────────────────────────────────────────
  let canvas, ctx, bgImage;
  let sceneData = null;       // {objects: [{id, x_min, …}], …}
  let waypoints = [];         // [{x, y, animation, facing, depth_m, frame}]
  let floorProfile = [];      // [[x, y_min, y_max], …] (display coords)
  let depthFlat = null;       // Float32Array (original resolution)
  let depthH = 0, depthW = 0;
  let depthCanvas = null;     // OffscreenCanvas (colourised depth, original resolution)

  let scale = 1;              // display / original pixel ratio
  let origW = 0, origH = 0;

  let dragging = -1;          // index of waypoint being dragged
  let dragOffX = 0, dragOffY = 0;
  let _selectedIndex = -1;

  const RADIUS       = 8;
  const COL_NORMAL   = "#ffd932";
  const COL_SELECTED = "#32dcff";
  const COL_LINE     = "rgba(200,200,200,0.7)";
  const COL_FLOOR    = "rgba(0,180,0,0.18)";
  const COL_BBOX     = "rgba(200,200,200,0.6)";
  // ── Helpers ───────────────────────────────────────────────────

  function toDisplay(ox, oy) { return [ox * scale, oy * scale]; }
  function toOriginal(dx, dy) { return [dx / scale, dy / scale]; }

  function hitTest(mx, my) {
    for (let i = waypoints.length - 1; i >= 0; i--) {
      const [dx, dy] = toDisplay(waypoints[i].x, waypoints[i].y);
      if (Math.hypot(mx - dx, my - dy) <= RADIUS + 4) return i;
    }
    return -1;
  }

  function depthAt(ox, oy) {
    if (!depthFlat) return null;
    const xi = Math.min(Math.max(Math.round(ox), 0), depthW - 1);
    const yi = Math.min(Math.max(Math.round(oy), 0), depthH - 1);
    return depthFlat[yi * depthW + xi];
  }

  function checkboxOn(id) {
    const el = document.getElementById(id);
    return el ? el.checked : false;
  }

  // ── Drawing ───────────────────────────────────────────────────

  function draw() {
    if (!ctx || !bgImage) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Background
    ctx.drawImage(bgImage, 0, 0, canvas.width, canvas.height);

    const playing = typeof Preview !== "undefined" && Preview.isPlaying();

    if (!playing) {
      // Depth overlay (drawImage scales the offscreen canvas to fit)
      if (checkboxOn("show-depth") && depthCanvas) {
        ctx.globalAlpha = 0.55;
        ctx.drawImage(depthCanvas, 0, 0, canvas.width, canvas.height);
        ctx.globalAlpha = 1.0;
      }

      // Floor overlay (column strips)
      if (checkboxOn("show-floor") && floorProfile.length) {
        ctx.fillStyle = COL_FLOOR;
        for (const [ox, yMin, yMax] of floorProfile) {
          const [dx] = toDisplay(ox, 0);
          const [, dyMin] = toDisplay(0, yMin);
          const [, dyMax] = toDisplay(0, yMax);
          ctx.fillRect(dx, dyMin, scale, dyMax - dyMin);
        }
      }

      // Object bounding boxes
      if (checkboxOn("show-bboxes") && sceneData) {
        ctx.strokeStyle = COL_BBOX;
        ctx.lineWidth   = 1.5;
        ctx.font        = "11px monospace";
        ctx.fillStyle   = "rgba(30,30,30,0.7)";
        for (const obj of sceneData.objects || []) {
          const [x1, y1] = toDisplay(obj.x_min, obj.y_min);
          const [x2, y2] = toDisplay(obj.x_max, obj.y_max);
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          ctx.fillRect(x1, y1, 120, 16);
          ctx.fillStyle = "#bbb";
          ctx.fillText(`${obj.id}  ${obj.base_depth_m.toFixed(2)}m`, x1 + 3, y1 + 11);
          ctx.fillStyle = "rgba(30,30,30,0.7)";
        }
      }

      // Path lines
      ctx.strokeStyle = COL_LINE;
      ctx.lineWidth   = 2;
      ctx.beginPath();
      for (let i = 0; i < waypoints.length; i++) {
        const [dx, dy] = toDisplay(waypoints[i].x, waypoints[i].y);
        i === 0 ? ctx.moveTo(dx, dy) : ctx.lineTo(dx, dy);
      }
      ctx.stroke();

      // Waypoints
      for (let i = 0; i < waypoints.length; i++) {
        const wp = waypoints[i];
        const [dx, dy] = toDisplay(wp.x, wp.y);
        const isSel    = i === _selectedIndex;

        ctx.beginPath();
        ctx.arc(dx, dy, RADIUS, 0, Math.PI * 2);
        ctx.fillStyle   = isSel ? COL_SELECTED : COL_NORMAL;
        ctx.fill();
        if (isSel) {
          ctx.strokeStyle = "#fff";
          ctx.lineWidth   = 2;
          ctx.stroke();
        }

        // Label
        const arrow = wp.facing === "right" ? "→" : "←";
        const d     = wp.depth_m != null ? ` ${wp.depth_m.toFixed(2)}m` : "";
        const label = `${i}: ${wp.animation} ${arrow}${d}`;
        ctx.font      = "11px monospace";
        ctx.fillStyle = "rgba(20,20,20,0.75)";
        const tw = ctx.measureText(label).width;
        ctx.fillRect(dx + RADIUS + 2, dy - 13, tw + 6, 16);
        ctx.fillStyle = isSel ? COL_SELECTED : "#eee";
        ctx.fillText(label, dx + RADIUS + 5, dy - 1);
      }
    }

    // Sprite preview — drawn on top of clean background
    if (playing) {
      Preview.drawFrame(ctx, canvas.height, scale);
    }
  }

  // ── Mouse events ──────────────────────────────────────────────

  function onMouseDown(e) {
    const rect = canvas.getBoundingClientRect();
    const mx   = (e.clientX - rect.left) * (canvas.width  / rect.width);
    const my   = (e.clientY - rect.top)  * (canvas.height / rect.height);

    const hit = hitTest(mx, my);
    if (hit >= 0) {
      dragging     = hit;
      _selectedIndex = hit;
      const [dx, dy] = toDisplay(waypoints[hit].x, waypoints[hit].y);
      dragOffX = mx - dx;
      dragOffY = my - dy;
    } else {
      _selectedIndex = -1;
    }
    draw();
    Editor._onSelectionChange();
  }

  function onMouseMove(e) {
    if (dragging < 0) return;
    const rect = canvas.getBoundingClientRect();
    const mx   = (e.clientX - rect.left) * (canvas.width  / rect.width);
    const my   = (e.clientY - rect.top)  * (canvas.height / rect.height);

    const [ox, oy] = toOriginal(mx - dragOffX, my - dragOffY);
    const wp = waypoints[dragging];
    wp.x       = Math.round(Math.max(0, Math.min(ox, origW - 1)));
    wp.y       = Math.round(Math.max(0, Math.min(oy, origH - 1)));
    wp.depth_m = depthAt(wp.x, wp.y);
    wp.frame   = dragging * parseInt(document.getElementById("frame-spacing").value || 20);
    draw();
    Editor._onKeypointsChange();
  }

  function onMouseUp() {
    dragging = -1;
  }

  // ── Public API ────────────────────────────────────────────────

  function init(canvasEl, bgImg, sd) {
    canvas    = canvasEl;
    ctx       = canvas.getContext("2d");
    bgImage   = bgImg;
    sceneData = sd;
    origW     = bgImg.naturalWidth;
    origH     = bgImg.naturalHeight;

    // Fit canvas inside the container using both dimensions so the canvas
    // intrinsic size always matches the displayed size (no CSS scaling).
    // This keeps sprite coordinates accurate.
    const containerW = canvas.parentElement.clientWidth;
    const containerH = canvas.parentElement.clientHeight || window.innerHeight * 0.6;
    const scaleW     = containerW / origW;
    const scaleH     = containerH / origH;
    scale            = Math.min(scaleW, scaleH);
    canvas.width     = Math.round(origW * scale);
    canvas.height    = Math.round(origH * scale);
    // Set explicit pixel dimensions so CSS never re-scales the canvas
    canvas.style.width  = canvas.width  + "px";
    canvas.style.height = canvas.height + "px";

    canvas.addEventListener("mousedown", onMouseDown);
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseup",   onMouseUp);
    canvas.addEventListener("mouseleave", onMouseUp);

    // Redraw when overlay checkboxes change
    ["show-depth", "show-floor", "show-bboxes"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", draw);
    });

    draw();
  }

  function loadKeypoints(kps, frameSpacing = 20) {
    waypoints = kps.map((kp, i) => ({
      x:         kp.foot_position[0],
      y:         kp.foot_position[1],
      animation: kp.animation || "idle",
      facing:    kp.facing    || "right",
      depth_m:   kp.depth_m   ?? depthAt(kp.foot_position[0], kp.foot_position[1]),
      frame:     kp.frame     ?? i * frameSpacing,
    }));
    _selectedIndex = -1;
    draw();
    Editor._onKeypointsChange();
  }

  function loadFloorProfile(profile) {
    floorProfile = profile;  // [[x, y_min, y_max], …] in original coords
    draw();
  }

  function getKeypoints(frameSpacing) {
    const spacing = frameSpacing || parseInt(document.getElementById("frame-spacing").value || 20);
    return waypoints.map((wp, i) => ({
      frame:         i * spacing,
      foot_position: [wp.x, wp.y],
      depth_m:       wp.depth_m ?? depthAt(wp.x, wp.y),
      facing:        wp.facing,
      animation:     wp.animation,
    }));
  }

  function clear() {
    waypoints      = [];
    floorProfile   = [];
    _selectedIndex = -1;
    draw();
    Editor._onKeypointsChange();
  }

  function setDepthArray(flat, h, w) {
    depthFlat = flat;
    depthH    = h;
    depthW    = w;
  }

  function setDepthImage(offscreenCanvas) {
    depthCanvas = offscreenCanvas;
    draw();
  }

  function redraw() { draw(); }

  return {
    init,
    loadKeypoints,
    loadFloorProfile,
    getKeypoints,
    clear,
    setDepthArray,
    setDepthImage,
    redraw,
    get selectedIndex() { return _selectedIndex; },
    get scale() { return scale; },
    // Hooks — overridden by main.js
    _onKeypointsChange: () => {},
    _onSelectionChange: () => {},
  };
})();
