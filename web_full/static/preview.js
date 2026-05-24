/**
 * preview.js
 *
 * Animates the pet sprite along the trajectory by drawing directly onto
 * the editor canvas each frame (no <img> overlay — avoids coordinate
 * mismatch with CSS-scaled canvases).
 *
 * White-background GIFs: the current frame is captured from a hidden <img>,
 * drawn to an OffscreenCanvas, and white pixels are zeroed out so the sprite
 * composites cleanly over the scene.
 *
 * Public API (used by main.js and canvas_editor.js):
 *   Preview.load(spritePaths)       – {animName: relativeUrl}
 *   Preview.start(keypoints, fps, scale)
 *   Preview.stop()
 *   Preview.isPlaying()
 *   Preview.drawFrame(ctx, canvasW, canvasH, scale)  – called by canvas_editor draw()
 */

const Preview = (() => {

  // Hidden <img> elements keyed by animation name (they play GIFs natively)
  const spriteImgs = {};

  let playing       = false;
  let startTime     = null;
  let currentFrame  = 0;
  let keypoints     = [];
  let fps           = 30;
  let rafId         = null;

  // Re-usable offscreen canvas for white-removal
  let offscreen     = null;

  // ── Trajectory interpolation ──────────────────────────────────

  function interpolate(frame) {
    if (!keypoints.length) return null;
    if (frame <= keypoints[0].frame) return { ...keypoints[0], x: keypoints[0].foot_position[0], y: keypoints[0].foot_position[1] };
    if (frame >= keypoints[keypoints.length - 1].frame) {
      const last = keypoints[keypoints.length - 1];
      return { ...last, x: last.foot_position[0], y: last.foot_position[1] };
    }
    for (let i = 0; i < keypoints.length - 1; i++) {
      const a = keypoints[i], b = keypoints[i + 1];
      if (frame >= a.frame && frame <= b.frame) {
        const t = (frame - a.frame) / (b.frame - a.frame);
        return {
          x:         a.foot_position[0] + t * (b.foot_position[0] - a.foot_position[0]),
          y:         a.foot_position[1] + t * (b.foot_position[1] - a.foot_position[1]),
          animation: a.animation,
          facing:    a.facing,
          depth_m:   a.depth_m != null ? a.depth_m + t * ((b.depth_m ?? a.depth_m) - a.depth_m) : null,
        };
      }
    }
    return null;
  }

  // ── Sprite size (perspective scale) ──────────────────────────
  // Base: 8% of canvas height at near_depth. Scales inversely with depth.
  function spriteDisplayH(depth_m, canvasH, nearDepth = 0.4) {
    const base = canvasH * 0.08;
    const d    = (depth_m && depth_m > 0) ? depth_m : nearDepth;
    return Math.max(20, Math.round(base * nearDepth / d));
  }

  // ── White-pixel removal ────────────────────────────────────────
  function removeWhite(imgEl, destW, destH) {
    if (!offscreen || offscreen.width !== destW || offscreen.height !== destH) {
      offscreen = new OffscreenCanvas(destW, destH);
    }
    const oc    = offscreen;
    const octx  = oc.getContext("2d");
    octx.clearRect(0, 0, destW, destH);
    try {
      octx.drawImage(imgEl, 0, 0, destW, destH);
    } catch { return null; }  // img not yet loaded

    const id   = octx.getImageData(0, 0, destW, destH);
    const data = id.data;
    for (let i = 0; i < data.length; i += 4) {
      // Remove near-white pixels (threshold 220/255 per channel)
      if (data[i] > 220 && data[i + 1] > 220 && data[i + 2] > 220) {
        data[i + 3] = 0;
      }
    }
    octx.putImageData(id, 0, 0);
    return oc;
  }

  // ── Animation RAF loop ─────────────────────────────────────────
  // Only tracks time and triggers Editor redraws. Actual drawing happens
  // in drawFrame(), called from canvas_editor.js's draw().

  function loop(timestamp) {
    if (!playing) return;
    if (!startTime) startTime = timestamp;

    const elapsed     = (timestamp - startTime) / 1000;
    const totalFrames = keypoints.length > 0
      ? keypoints[keypoints.length - 1].frame
      : 1;
    currentFrame = (elapsed * fps) % (totalFrames + fps * 0.5);

    // Ask the editor to redraw (it will call drawFrame at the end of draw())
    if (typeof Editor !== "undefined") Editor.redraw();

    rafId = requestAnimationFrame(loop);
  }

  // ── drawFrame (called by canvas_editor.js draw()) ──────────────

  function drawFrame(ctx, canvasH, displayScale) {
    if (!playing) return;
    const state = interpolate(Math.round(currentFrame));
    if (!state) return;

    const imgEl = spriteImgs[state.animation] || spriteImgs["idle"] || spriteImgs[Object.keys(spriteImgs)[0]];
    if (!imgEl || !imgEl.complete || imgEl.naturalWidth === 0) return;

    const sz   = spriteDisplayH(state.depth_m, canvasH);
    const szW  = Math.round(sz * (imgEl.naturalWidth / imgEl.naturalHeight));
    const px   = Math.round(state.x * displayScale);
    const py   = Math.round(state.y * displayScale);

    const processed = removeWhite(imgEl, szW, sz);
    if (!processed) return;

    ctx.save();
    if (state.facing === "left") {
      // Flip horizontally around the foot centre
      ctx.scale(-1, 1);
      ctx.drawImage(processed, -(px + szW / 2), py - sz, szW, sz);
    } else {
      ctx.drawImage(processed, px - szW / 2, py - sz, szW, sz);
    }
    ctx.restore();
  }

  // ── Public ─────────────────────────────────────────────────────

  function load(paths) {
    // Remove old hidden elements
    document.querySelectorAll(".preview-sprite-img").forEach(el => el.remove());

    for (const [name, url] of Object.entries(paths)) {
      const img    = document.createElement("img");
      img.src      = url;
      img.className = "preview-sprite-img";
      img.style.cssText = "position:absolute;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none";
      document.body.appendChild(img);
      spriteImgs[name] = img;
    }
  }

  function start(kps, fpsVal) {
    stop();
    if (!kps || kps.length < 2) return;
    keypoints = kps;
    fps       = fpsVal || 30;
    playing   = true;
    startTime   = null;
    currentFrame = 0;
    rafId = requestAnimationFrame(loop);
  }

  function stop() {
    playing = false;
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    startTime    = null;
    currentFrame = 0;
    if (typeof Editor !== "undefined") Editor.redraw();
  }

  function isPlaying() { return playing; }

  return { load, start, stop, isPlaying, drawFrame };
})();
