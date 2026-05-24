#!/usr/bin/env python3
"""
web_full/server.py

Flask server for DigitalPet Architecture B: full server-side pipeline.
The browser handles the trajectory editor (pure JS), while the real Python
pipeline (auto_trajectory, trajectory_optimizer, compositor) runs here.

Start from the project root:
    python web_full/server.py \
        --scene-json  output/scenes/desk/processed_scene/scene_processed.json \
        --char-json   output/pets/Fluffball/character.json \
        [--output-dir web_full/output] [--port 5000]

Endpoints
─────────
  GET  /                         → index.html
  GET  /api/scene                → scene metadata + media URLs
  GET  /api/media/background     → background image (JPEG)
  GET  /api/media/depth-overlay  → depth overlay PNG (plasma colourmap)
  GET  /api/media/sprite/<name>  → sprite GIF for animation <name>
  POST /api/generate             → run auto_trajectory; returns keypoints + floor_profile
  POST /api/optimize             → run trajectory_optimizer; returns keypoints + intersections
  POST /api/composite            → start async compositor; returns job_id
  GET  /api/job/<job_id>         → poll compositor job status
  GET  /api/download/<filename>  → download any file from output dir
"""

import argparse
import io
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

# ── Add project root to sys.path so src.* imports work ───────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.compositor.auto_trajectory import (
    load_scene as _load_scene,
    build_floor_mask,
    trace_floor_profile,
    generate as _at_generate,
)
from src.compositor.trajectory_optimizer import (
    find_intersections,
    decide_strategy,
    optimize as _to_optimize,
    STRATEGY_COLOURS,
)
from src.compositor.compositor import composite as _composite

app = Flask(__name__, static_folder="static", static_url_path="")

# ── Runtime config (set by main()) ────────────────────────────────
SCENE_JSON = None   # Path
CHAR_JSON  = None   # Path
OUTPUT_DIR = None   # Path

# ── Cached heavy data ─────────────────────────────────────────────
_scene      = None   # {h, w, bg, depth_m, near_depth_m, objects}
_char_data  = None   # parsed character.json
_scene_lock = threading.Lock()

# ── Compositor jobs ───────────────────────────────────────────────
_jobs      = {}   # job_id → {status, t_start, output, error}
_jobs_lock = threading.Lock()

# STRATEGY_COLOURS stores RGB values — convert to CSS hex for the browser
STRAT_HEX = {
    s: "#{:02x}{:02x}{:02x}".format(*rgb)
    for s, rgb in STRATEGY_COLOURS.items()
}


# ── Scene helpers ─────────────────────────────────────────────────

def _get_scene():
    """Load and cache the scene (reads depth map + masks; slow on first call)."""
    global _scene
    with _scene_lock:
        if _scene is None:
            print("Loading scene (first call — may take a moment)…")
            _scene = _load_scene(str(SCENE_JSON))
            print(f"  Scene ready: {_scene['w']}×{_scene['h']}  "
                  f"near_depth={_scene['near_depth_m']:.2f}m  "
                  f"objects={len(_scene['objects'])}")
    return _scene


def _get_char():
    global _char_data
    if _char_data is None:
        with open(CHAR_JSON) as f:
            _char_data = json.load(f)
    return _char_data


def _depth_overlay_path():
    return OUTPUT_DIR / "depth_overlay.png"


def _build_depth_overlay():
    """Compute plasma-colourmap depth overlay and save as PNG (idempotent)."""
    out = _depth_overlay_path()
    if out.exists():
        return
    scene = _get_scene()
    d = scene["depth_m"]
    d_min, d_max = float(d.min()), float(d.max())
    t = (d - d_min) / (d_max - d_min + 1e-8)

    # 8-stop plasma LUT (matches the browser-side approximation)
    PLASMA = np.array([
        [13,  8,135],[84,  2,163],[139, 10,165],[185, 50,137],
        [219, 92,104],[244,136, 73],[254,188, 43],[240,249, 33],
    ], dtype=np.float32)

    s   = t * (len(PLASMA) - 1)
    idx = np.clip(np.floor(s).astype(np.int32), 0, len(PLASMA) - 2)
    f   = (s - idx)[..., np.newaxis]
    rgb = np.clip(PLASMA[idx] + f * (PLASMA[idx + 1] - PLASMA[idx]), 0, 255).astype(np.uint8)
    bgr = rgb[:, :, ::-1]   # convert RGB → BGR for cv2
    cv2.imwrite(str(out), bgr)
    print(f"Depth overlay written → {out}")


def _warmup():
    """Pre-load scene and depth overlay in a background thread at startup."""
    _get_scene()
    _build_depth_overlay()


def _read_scene_json():
    with open(SCENE_JSON) as f:
        return json.load(f)


def _objects_for_optimizer(scene_raw, scene):
    """Convert scene_processed.json objects to the format find_intersections expects."""
    return [
        {
            "id":           obj["id"],
            "x_min":        int(obj.get("x_min", 0)),
            "x_max":        int(obj.get("x_max", scene["w"])),
            "y_min":        int(obj.get("y_min", 0)),
            "y_max":        int(obj.get("y_max", scene["h"])),
            "base_depth_m": float(obj.get("base_depth_m", 1.0)),
        }
        for obj in scene_raw.get("objects", [])
    ]


# ── Static ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ── Media endpoints ───────────────────────────────────────────────

@app.route("/api/media/background")
def media_background():
    scene = _get_scene()
    ok, buf = cv2.imencode(".jpg", scene["bg"], [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        abort(500)
    return send_file(io.BytesIO(buf.tobytes()), mimetype="image/jpeg")


@app.route("/api/media/depth-overlay")
def media_depth_overlay():
    _build_depth_overlay()
    return send_file(str(_depth_overlay_path()), mimetype="image/png")


@app.route("/api/media/sprite/<name>")
def media_sprite(name):
    char  = _get_char()
    anims = char.get("animations", {})
    if name not in anims:
        abort(404)
    gif_rel  = anims[name].get("gif", "")
    gif_path = CHAR_JSON.parent / gif_rel
    if not gif_path.exists():
        abort(404)
    return send_file(str(gif_path), mimetype="image/gif")


# ── Scene metadata ────────────────────────────────────────────────

@app.route("/api/scene")
def api_scene():
    scene     = _get_scene()
    char      = _get_char()
    scene_raw = _read_scene_json()

    objects_out = [
        {
            "id":           obj["id"],
            "x_min":        int(obj.get("x_min", 0)),
            "y_min":        int(obj.get("y_min", 0)),
            "x_max":        int(obj.get("x_max", scene["w"])),
            "y_max":        int(obj.get("y_max", scene["h"])),
            "base_depth_m": float(obj.get("base_depth_m", scene["near_depth_m"])),
        }
        for obj in scene_raw.get("objects", [])
    ]

    sprites = {
        name: f"/api/media/sprite/{name}"
        for name in char.get("animations", {})
    }

    return jsonify({
        "image_url":         "/api/media/background",
        "depth_overlay_url": "/api/media/depth-overlay",
        "image_w":           scene["w"],
        "image_h":           scene["h"],
        "near_depth_m":      scene["near_depth_m"],
        "fps":               30,
        "objects":           objects_out,
        "sprites":           sprites,
    })


# ── Generate auto trajectory ──────────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def api_generate():
    params    = request.json or {}
    auto_path = str(OUTPUT_DIR / "auto_trajectory.json")

    floor_y_frac = float(params.get("floor_y_frac", 0.45))
    max_depth_m  = float(params.get("max_depth_m",  2.0))

    try:
        _at_generate(
            scene_json=str(SCENE_JSON),
            character_json=str(CHAR_JSON),
            output_path=auto_path,
            n_keypoints=int(params.get("n_keypoints",  10)),
            frame_spacing=int(params.get("frame_spacing", 20)),
            fps=int(params.get("fps",           30)),
            floor_y_frac=floor_y_frac,
            max_depth_m=max_depth_m,
            path_style=params.get("path_style",   "sweep"),
            start_y_frac=float(params.get("start_y_frac",  0.90)),
            end_y_frac=float(params.get("end_y_frac",    0.55)),
            seed=int(params.get("seed",          42)),
            visualize=True,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    with open(auto_path) as f:
        traj = json.load(f)
    keypoints = traj["trajectory"]["keypoints"]
    fps       = traj["trajectory"].get("fps", 30)

    # Compute floor profile for the browser editor overlay.
    # auto_trajectory.generate() computes it internally; we re-run it here
    # since the function doesn't expose it in the output JSON.
    try:
        scene      = _get_scene()
        floor_mask = build_floor_mask(scene, floor_y_frac, max_depth_m)
        profile    = trace_floor_profile(floor_mask, scene["h"], scene["w"])
        floor_profile = [[x, ylo, yhi] for x, (ylo, yhi) in sorted(profile.items())]
    except Exception:
        floor_profile = []

    return jsonify({
        "keypoints":     keypoints,
        "floor_profile": floor_profile,
        "fps":           fps,
    })


# ── Run trajectory optimizer ──────────────────────────────────────

@app.route("/api/optimize", methods=["POST"])
def api_optimize():
    params    = request.json or {}
    keypoints = params.get("keypoints", [])
    strategy  = params.get("strategy",      "auto")
    d_margin  = float(params.get("depth_margin",  0.04))
    a_margin  = int(params.get("around_margin", 30))

    if not keypoints:
        return jsonify({"error": "No keypoints provided"}), 400

    # Write the current keypoints to a temp file for the optimizer
    tmp_traj_path = str(OUTPUT_DIR / "_tmp_trajectory.json")
    with open(tmp_traj_path, "w") as f:
        json.dump({
            "trajectory": {
                "scene_ref":     str(SCENE_JSON),
                "character_ref": str(CHAR_JSON),
                "fps":           30,
                "keypoints":     keypoints,
            }
        }, f)

    opt_path = str(OUTPUT_DIR / "optimized_trajectory.json")
    try:
        _to_optimize(
            trajectory_json=tmp_traj_path,
            scene_json=str(SCENE_JSON),
            output_path=opt_path,
            strategy=strategy,
            depth_margin=d_margin,
            around_margin=a_margin,
            visualize=True,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    with open(opt_path) as f:
        opt_traj = json.load(f)
    opt_keypoints = opt_traj["trajectory"]["keypoints"]

    # Re-run intersection detection so we can return strategy info for the browser viz
    scene     = _get_scene()
    scene_raw = _read_scene_json()
    objs      = _objects_for_optimizer(scene_raw, scene)
    ixs_raw   = find_intersections(keypoints, objs)
    for ix in ixs_raw:
        ix["strategy"] = decide_strategy(
            ix, keypoints, scene["depth_m"], scene["h"], scene["w"], strategy
        )

    intersections_out = [
        {
            "obj_id":   ix["obj"]["id"],
            "strategy": ix["strategy"],
            "enter_xy": list(ix["enter_xy"]),
            "exit_xy":  list(ix["exit_xy"]),
        }
        for ix in ixs_raw
    ]

    return jsonify({
        "keypoints":        opt_keypoints,
        "intersections":    intersections_out,
        "strategy_colours": STRAT_HEX,
    })


# ── Composite video (async) ───────────────────────────────────────

@app.route("/api/composite", methods=["POST"])
def api_composite():
    params    = request.json or {}
    keypoints = params.get("keypoints")   # current browser keypoints (may be edited)

    if not keypoints:
        return jsonify({"error": "No keypoints provided. Generate a trajectory first."}), 400

    job_id       = uuid.uuid4().hex[:12]
    output_video = str(OUTPUT_DIR / f"composite_{job_id}.mp4")

    # Write keypoints to a dedicated input file for this job
    job_traj_path = str(OUTPUT_DIR / f"composite_{job_id}_input.json")
    with open(job_traj_path, "w") as f:
        json.dump({
            "trajectory": {
                "scene_ref":     str(SCENE_JSON),
                "character_ref": str(CHAR_JSON),
                "fps":           params.get("fps", 30),
                "keypoints":     keypoints,
            }
        }, f)

    with _jobs_lock:
        _jobs[job_id] = {
            "status":  "running",
            "t_start": time.time(),
            "output":  output_video,
            "error":   None,
        }

    def _run():
        try:
            _composite(
                scene_json=str(SCENE_JSON),
                trajectory_json=job_traj_path,
                character_json=str(CHAR_JSON),
                output_video=output_video,
                global_scale=float(params.get("global_scale", 1.0)),
                depth_tolerance_m=float(params.get("depth_tolerance_m", 0.0)),
            )
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"]  = str(exc)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def api_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        abort(404)

    elapsed = time.time() - job["t_start"]
    resp = {
        "status":    job["status"],
        "elapsed_s": round(elapsed, 1),
        "error":     job["error"],
    }
    if job["status"] == "done":
        resp["download_url"] = f"/api/download/{Path(job['output']).name}"
    return jsonify(resp)


# ── Downloads ─────────────────────────────────────────────────────

@app.route("/api/download/<filename>")
def api_download(filename):
    # Sanitize: only serve files that live directly in OUTPUT_DIR
    safe = OUTPUT_DIR / Path(filename).name
    if not safe.exists():
        abort(404)
    return send_file(str(safe), as_attachment=True, download_name=filename)


# ── Entry point ───────────────────────────────────────────────────

def main():
    global SCENE_JSON, CHAR_JSON, OUTPUT_DIR

    parser = argparse.ArgumentParser(
        description="DigitalPet web server — Architecture B (full pipeline)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--scene-json",  required=True,
                        help="Path to scene_processed.json")
    parser.add_argument("--char-json",   required=True,
                        help="Path to character.json")
    parser.add_argument("--output-dir",  default="web_full/output",
                        help="Output directory for generated files (default: web_full/output)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    SCENE_JSON = Path(args.scene_json).resolve()
    CHAR_JSON  = Path(args.char_json).resolve()
    OUTPUT_DIR = Path(args.output_dir).resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for p, label in [(SCENE_JSON, "--scene-json"), (CHAR_JSON, "--char-json")]:
        if not p.exists():
            print(f"ERROR: {label} not found: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"\nDigitalPet Server (Architecture B)")
    print(f"  Scene:      {SCENE_JSON}")
    print(f"  Character:  {CHAR_JSON}")
    print(f"  Output dir: {OUTPUT_DIR}")
    print(f"  URL:        http://{args.host}:{args.port}/\n")

    # Warm up scene + depth overlay in background so the first request is fast
    threading.Thread(target=_warmup, daemon=True).start()

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
