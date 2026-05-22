"""
trajectory_tool.py

Interactive click-to-place trajectory authoring tool.

Left-click points on the scene image to lay down keypoints for the pet's
path. Frame numbers are assigned automatically based on --frame-spacing so
you don't need to think in frames.

Controls
────────
  Left-click          Place a keypoint at the cursor
  Right-click         Remove the last keypoint
  A / D               Cycle animation backward / forward for selected point
  F                   Toggle facing left ↔ right for selected point
  Tab                 Select next keypoint
  Shift-Tab           Select previous keypoint
  O                   Toggle depth-map overlay (shows near=bright/far=dark)
  S                   Save trajectory JSON and quit
  Q  or  Esc          Quit without saving

Usage
─────
  python -m src.compositor.trajectory_tool \\
      --scene-json     output/scenes/desk/processed_scene/scene_processed.json \\
      --character-json output/pets/Fluffball/character.json \\
      --output         scene_input/desk_trajectory.json

Options
───────
  --frame-spacing N   Frames between consecutive click points (default 20)
  --fps N             FPS written into the trajectory JSON (default 30)
  --display-scale F   Shrink display for large images, e.g. 0.5 for 4K.
                      Coordinates are saved at original resolution.
"""

import argparse
import json
import os
from pathlib import Path

import cv2
import numpy as np


# ──────────────────────────────────────────────
# DRAWING CONSTANTS
# ──────────────────────────────────────────────

POINT_RADIUS = 8
FONT         = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE   = 0.52
FONT_THICK   = 1
LINE_THICK   = 2

COL_POINT    = (255, 220,  50)   # yellow — unselected keypoint
COL_SELECTED = ( 50, 220, 255)   # cyan   — selected keypoint
COL_LINE     = (200, 200, 200)   # light grey connecting line
COL_TEXT_BG  = ( 30,  30,  30)
COL_TEXT_FG  = (255, 255, 255)
HUD_BG       = ( 20,  20,  20)
HUD_FG       = (220, 220, 220)
HUD_DIM      = (160, 160, 160)


# ──────────────────────────────────────────────
# STATE
# ──────────────────────────────────────────────

class _Keypoint:
    __slots__ = ("x", "y", "anim_idx", "facing")

    def __init__(self, x, y, anim_idx=0, facing="right"):
        self.x        = x
        self.y        = y
        self.anim_idx = anim_idx
        self.facing   = facing


class State:
    def __init__(self, bg_image, depth_m, animations, fps, frame_spacing):
        self.bg            = bg_image
        self.depth_m       = depth_m
        self.h, self.w     = bg_image.shape[:2]
        self.animations    = animations      # sorted list of action name strings
        self.fps           = fps
        self.frame_spacing = frame_spacing

        self.keypoints: list[_Keypoint] = []
        self.selected  = -1              # index of currently selected point
        self.show_depth = False
        self.dirty      = False

    # ── editing ──────────────────────────────

    def add(self, x, y):
        anim_idx = self.keypoints[self.selected].anim_idx if self.selected >= 0 else 0
        self.keypoints.append(_Keypoint(x, y, anim_idx=anim_idx))
        self.selected = len(self.keypoints) - 1
        self.dirty = True

    def remove_last(self):
        if not self.keypoints:
            return
        self.keypoints.pop()
        self.selected = len(self.keypoints) - 1
        self.dirty = True

    def cycle_anim(self, delta: int):
        if self.selected < 0 or not self.animations:
            return
        kp = self.keypoints[self.selected]
        kp.anim_idx = (kp.anim_idx + delta) % len(self.animations)
        self.dirty = True

    def toggle_facing(self):
        if self.selected < 0:
            return
        kp = self.keypoints[self.selected]
        kp.facing = "left" if kp.facing == "right" else "right"
        self.dirty = True

    def select_delta(self, delta: int):
        if not self.keypoints:
            return
        self.selected = (self.selected + delta) % len(self.keypoints)

    # ── depth query ──────────────────────────

    def depth_at(self, kp: _Keypoint) -> float | None:
        if self.depth_m is None:
            return None
        yc = min(max(kp.y, 0), self.h - 1)
        xc = min(max(kp.x, 0), self.w - 1)
        return float(self.depth_m[yc, xc])


# ──────────────────────────────────────────────
# RENDERING
# ──────────────────────────────────────────────

def _put_label(img, text, x, y):
    (tw, th), baseline = cv2.getTextSize(text, FONT, FONT_SCALE, FONT_THICK)
    pad = 3
    cv2.rectangle(img,
                  (x - pad,      y - th - pad),
                  (x + tw + pad, y + baseline + pad),
                  COL_TEXT_BG, -1)
    cv2.putText(img, text, (x, y), FONT, FONT_SCALE,
                COL_TEXT_FG, FONT_THICK, cv2.LINE_AA)


def render(state: State) -> np.ndarray:
    canvas = state.bg.copy()

    # Depth overlay
    if state.show_depth and state.depth_m is not None:
        d_norm    = cv2.normalize(state.depth_m, None, 0, 255,
                                  cv2.NORM_MINMAX).astype(np.uint8)
        coloured  = cv2.applyColorMap(d_norm, cv2.COLORMAP_PLASMA)
        canvas    = cv2.addWeighted(canvas, 0.6, coloured, 0.4, 0)

    # Connecting lines
    for i in range(len(state.keypoints) - 1):
        a, b = state.keypoints[i], state.keypoints[i + 1]
        cv2.line(canvas, (a.x, a.y), (b.x, b.y),
                 COL_LINE, LINE_THICK, cv2.LINE_AA)

    # Keypoint circles + labels
    for i, kp in enumerate(state.keypoints):
        is_sel = (i == state.selected)
        colour = COL_SELECTED if is_sel else COL_POINT
        cv2.circle(canvas, (kp.x, kp.y), POINT_RADIUS, colour, -1 if is_sel else 2)

        anim  = state.animations[kp.anim_idx] if state.animations else "?"
        arrow = "→" if kp.facing == "right" else "←"
        label = f"{i}: {anim} {arrow}"
        d = state.depth_at(kp)
        if d is not None:
            label += f"  {d:.2f}m"

        _put_label(canvas, label,
                   kp.x + POINT_RADIUS + 4,
                   kp.y - POINT_RADIUS)

    # HUD strip at the bottom
    hud_h = 52
    cv2.rectangle(canvas, (0, state.h - hud_h), (state.w, state.h), HUD_BG, -1)

    info = (f"  {len(state.keypoints)} pts | "
            f"spacing={state.frame_spacing}fr | fps={state.fps} | "
            f"depth={'ON' if state.show_depth else 'off'}")
    if state.selected >= 0 and state.keypoints:
        kp   = state.keypoints[state.selected]
        anim = state.animations[kp.anim_idx] if state.animations else "?"
        d    = state.depth_at(kp)
        info += (f"  |  #{state.selected} ({kp.x},{kp.y})  "
                 f"anim={anim}  facing={kp.facing}"
                 + (f"  depth={d:.2f}m" if d is not None else ""))

    cv2.putText(canvas, info,
                (8, state.h - hud_h + 18), FONT, 0.46, HUD_FG, 1, cv2.LINE_AA)
    cv2.putText(canvas,
                "L-click=add  R-click=undo  A/D=anim  F=facing  "
                "Tab/Shift-Tab=select  O=depth  S=save+quit  Q=quit",
                (8, state.h - hud_h + 38), FONT, 0.42, HUD_DIM, 1, cv2.LINE_AA)

    return canvas


# ──────────────────────────────────────────────
# MOUSE CALLBACK
# ──────────────────────────────────────────────

def _make_mouse_cb(state: State):
    def cb(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            state.add(x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            state.remove_last()
    return cb


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def run(scene_json: str,
        character_json: str,
        output_path: str,
        frame_spacing: int = 20,
        fps: int = 30,
        display_scale: float = 1.0):

    # ── Load scene ──
    with open(scene_json) as f:
        scene_data = json.load(f)

    image_path = scene_data["scene"]["image_path"]
    bg = cv2.imread(image_path)
    if bg is None:
        raise FileNotFoundError(f"Scene image not found: {image_path}")

    # ── Load depth map ──
    depth_m = None
    dp = (scene_data.get("depth_map_path")
          or scene_data["scene"].get("depth_map_path"))
    if dp and os.path.exists(dp):
        depth_m = np.load(dp)
        if depth_m.shape[:2] != bg.shape[:2]:
            depth_m = cv2.resize(depth_m, (bg.shape[1], bg.shape[0]),
                                 interpolation=cv2.INTER_LINEAR)

    # ── Load animation names from character.json ──
    animations = ["idle"]
    if os.path.exists(character_json):
        with open(character_json) as f:
            char_data = json.load(f)
        if "animations" in char_data:
            animations = sorted(char_data["animations"].keys())

    print(f"Scene image  : {image_path}  ({bg.shape[1]}x{bg.shape[0]})")
    print(f"Depth map    : {'loaded' if depth_m is not None else 'NOT found — depth labels will be hidden'}")
    print(f"Animations   : {animations}")
    print(f"Output       : {output_path}")
    print(f"Frame spacing: {frame_spacing}  (each click = +{frame_spacing} frames)")
    print()

    # ── Scale image for display if needed ──
    if display_scale != 1.0:
        dw = int(bg.shape[1] * display_scale)
        dh = int(bg.shape[0] * display_scale)
        bg_display    = cv2.resize(bg, (dw, dh))
        depth_display = (cv2.resize(depth_m, (dw, dh), interpolation=cv2.INTER_LINEAR)
                         if depth_m is not None else None)
    else:
        bg_display    = bg
        depth_display = depth_m

    state = State(bg_display, depth_display, animations, fps, frame_spacing)

    win = "Trajectory Tool — S=save  Q=quit"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, state.w, min(state.h, 900))
    cv2.setMouseCallback(win, _make_mouse_cb(state))

    while True:
        cv2.imshow(win, render(state))
        key = cv2.waitKey(30) & 0xFF

        if key in (ord('q'), 27):          # Q / Esc
            print("Quit without saving.")
            cv2.destroyAllWindows()
            return
        elif key == ord('s'):              # S — save + quit
            break
        elif key == ord('a'):              # A — prev animation
            state.cycle_anim(-1)
        elif key == ord('d'):              # D — next animation
            state.cycle_anim(+1)
        elif key == ord('f'):              # F — flip facing
            state.toggle_facing()
        elif key == ord('o'):              # O — depth overlay
            state.show_depth = not state.show_depth
        elif key == 9:                     # Tab — select next
            state.select_delta(+1)
        elif key in (353, 161):            # Shift-Tab — select prev
            state.select_delta(-1)

    cv2.destroyAllWindows()

    if not state.keypoints:
        print("No keypoints placed — nothing saved.")
        return

    # Build output keypoints, scaling coordinates back to original resolution
    inv = 1.0 / display_scale
    out_keypoints = []
    for i, kp in enumerate(state.keypoints):
        anim = animations[kp.anim_idx] if animations else "idle"
        out_keypoints.append({
            "frame":         i * frame_spacing,
            "foot_position": [int(round(kp.x * inv)), int(round(kp.y * inv))],
            "facing":        kp.facing,
            "animation":     anim,
        })

    trajectory = {
        "trajectory": {
            "scene_ref":     scene_json,
            "character_ref": character_json,
            "fps":           fps,
            "keypoints":     out_keypoints,
        }
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(trajectory, f, indent=2)

    print(f"\nSaved {len(out_keypoints)} keypoints -> {output_path}")
    print(f"{'#':<4}  {'frame':>5}  {'pos':^16}  {'animation':<16}  facing")
    print("-" * 58)
    for kp in out_keypoints:
        pos = f"({kp['foot_position'][0]},{kp['foot_position'][1]})"
        print(f"{out_keypoints.index(kp):<4}  {kp['frame']:>5}  "
              f"{pos:^16}  {kp['animation']:<16}  {kp['facing']}")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--scene-json",     required=True,
                        help="Path to scene_processed.json")
    parser.add_argument("--character-json", required=True,
                        help="Path to character.json (provides animation list)")
    parser.add_argument("--output",         required=True,
                        help="Output trajectory JSON path")
    parser.add_argument("--frame-spacing",  type=int, default=20,
                        help="Frames between consecutive click points (default: 20)")
    parser.add_argument("--fps",            type=int, default=30,
                        help="FPS written into the trajectory JSON (default: 30)")
    parser.add_argument("--display-scale",  type=float, default=1.0,
                        help="Scale the display window for large images "
                             "(e.g. 0.5 halves width/height). "
                             "Coordinates are saved at original resolution.")
    args = parser.parse_args()

    run(
        scene_json=args.scene_json,
        character_json=args.character_json,
        output_path=args.output,
        frame_spacing=args.frame_spacing,
        fps=args.fps,
        display_scale=args.display_scale,
    )
