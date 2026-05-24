/**
 * canvas_viz.js
 *
 * Draws a read-only trajectory visualization onto a canvas element.
 * Used for the side-by-side comparison panel (auto vs optimized).
 *
 * Renders at the original image resolution so labels are crisp and
 * non-overlapping. CSS (width:100%; height:auto) handles display scaling.
 *
 * Public API:
 *   CanvasViz.draw(canvasEl, bgImage, keypoints, objects, options)
 *
 * options:
 *   floorProfile    [[x, yMin, yMax], …]  (optional, for auto panel)
 *   intersections   [{obj_id, strategy, enter_xy, exit_xy}, …]
 *   strategyColours {strategy: hex}
 *   insertedSet     Set of frame numbers that are inserted (highlighted)
 *   title           string (drawn in top-left corner)
 */

const CanvasViz = (() => {

  const STRATEGY_COLS = {
    front:  "#32c832",
    behind: "#3264dc",
    ontop:  "#ffa01e",
    around: "#b432dc",
  };

  const COL_ORIGINAL = "rgba(200,200,200,0.9)";
  const COL_INSERTED = "#32dcff";
  const COL_BBOX_DEF = "rgba(120,120,120,0.8)";
  const COL_FLOOR    = "rgba(0,180,0,0.18)";

  function draw(canvasEl, bgImage, keypoints, objects, options = {}) {
    if (!canvasEl || !bgImage) return;

    const {
      floorProfile    = [],
      intersections   = [],
      strategyColours = STRATEGY_COLS,
      insertedSet     = new Set(),
      title           = "",
    } = options;

    // ── Render at full original resolution ─────────────────────
    // CSS (width:100%; height:auto) handles display scaling.
    // This ensures labels and dots are crisp and non-overlapping.
    const W = bgImage.naturalWidth;
    const H = bgImage.naturalHeight;
    canvasEl.width  = W;
    canvasEl.height = H;
    canvasEl.style.width  = "100%";
    canvasEl.style.height = "auto";
    canvasEl.style.display = "block";

    const ctx = canvasEl.getContext("2d");
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(bgImage, 0, 0, W, H);

    // ── Floor overlay ───────────────────────────────────────────
    if (floorProfile.length) {
      ctx.fillStyle = COL_FLOOR;
      for (const [x, yMin, yMax] of floorProfile) {
        ctx.fillRect(x, yMin, 1, yMax - yMin);
      }
    }

    // ── Object bounding boxes ───────────────────────────────────
    ctx.font = "24px monospace";
    for (const obj of objects) {
      const ix = intersections.find(i => i.obj_id === obj.id);
      ctx.strokeStyle = ix ? (strategyColours[ix.strategy] || COL_BBOX_DEF) : COL_BBOX_DEF;
      ctx.lineWidth   = ix ? 3 : 1.5;
      ctx.strokeRect(obj.x_min, obj.y_min, obj.x_max - obj.x_min, obj.y_max - obj.y_min);

      if (ix) {
        const label = `${obj.id} [${ix.strategy}]  ${obj.base_depth_m.toFixed(2)}m`;
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(15,15,15,0.75)";
        ctx.fillRect(obj.x_min + 3, obj.y_min + 3, tw + 10, 32);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.fillText(label, obj.x_min + 8, obj.y_min + 27);
      } else {
        const tw = ctx.measureText(obj.id).width;
        ctx.fillStyle = "rgba(15,15,15,0.6)";
        ctx.fillRect(obj.x_min + 3, obj.y_min + 3, tw + 8, 30);
        ctx.fillStyle = COL_BBOX_DEF;
        ctx.fillText(obj.id, obj.x_min + 7, obj.y_min + 25);
      }
    }

    // ── Path segments ───────────────────────────────────────────
    // Build a map: which original-keypoint frame ranges are covered by a strategy
    const stratRanges = intersections.map(ix => ({
      col:     strategyColours[ix.strategy] || COL_ORIGINAL,
      enterXY: ix.enter_xy,
      exitXY:  ix.exit_xy,
    }));

    function segColour(ax, ay, bx, by) {
      for (const r of stratRanges) {
        const ex = r.enterXY[0], ey = r.enterXY[1];
        const fx = r.exitXY[0],  fy = r.exitXY[1];
        const nearEnter = Math.hypot(ax - ex, ay - ey) < 30 || Math.hypot(bx - ex, by - ey) < 30;
        const nearExit  = Math.hypot(ax - fx, ay - fy) < 30 || Math.hypot(bx - fx, by - fy) < 30;
        if (nearEnter || nearExit) return r.col;
      }
      return COL_ORIGINAL;
    }

    ctx.lineWidth = 3;
    for (let i = 0; i < keypoints.length - 1; i++) {
      const a = keypoints[i].foot_position;
      const b = keypoints[i + 1].foot_position;
      ctx.strokeStyle = segColour(a[0], a[1], b[0], b[1]);
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();
    }

    // ── Waypoints ───────────────────────────────────────────────
    ctx.font = "22px monospace";
    for (const kp of keypoints) {
      const [px, py] = kp.foot_position;
      const isInsert = insertedSet.has(kp.frame);
      const radius   = isInsert ? 14 : 10;
      const col      = isInsert ? COL_INSERTED : "#c8c832";

      ctx.beginPath();
      ctx.arc(px, py, radius, 0, Math.PI * 2);
      ctx.fillStyle = col;
      ctx.fill();

      if (isInsert) {
        const d     = kp.depth_m != null ? ` ${kp.depth_m.toFixed(2)}m` : "";
        const label = `${kp.animation}${d}`;
        const tw    = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(15,15,15,0.75)";
        ctx.fillRect(px + 18, py - 18, tw + 10, 28);
        ctx.fillStyle = COL_INSERTED;
        ctx.fillText(label, px + 23, py + 4);
      }
    }

    // ── Title ───────────────────────────────────────────────────
    if (title) {
      ctx.font = "bold 30px system-ui";
      const tw = ctx.measureText(title).width;
      ctx.fillStyle = "rgba(0,0,0,0.65)";
      ctx.fillRect(8, 8, tw + 20, 42);
      ctx.fillStyle = "#fff";
      ctx.fillText(title, 18, 38);
    }
  }

  return { draw };
})();
