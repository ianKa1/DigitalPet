"""
trajectory_authoring.py

Manual trajectory authoring tool for the compositor.

Loads a labeled scene (post `scene_labeler`) and opens a matplotlib window
showing the scene image with every object mask outlined and labeled. Left-click
to drop a foot point. The tool handles three semantic chores automatically:

  1. **Point-in-mask check.** If the click lands inside an object mask, you're
     prompted (in the terminal) whether to add it to the new keypoint's
     `on_top_of`. Multiple masks at the same pixel are prompted one at a time.

  2. **Line-crossing check.** The straight-line interpolation from the
     previous keypoint to the new one is rasterised and checked against every
     object mask. Any mask the line crosses that isn't already in either
     endpoint's `on_top_of` triggers a prompt: "this segment passes through
     X, add on_top_of for both endpoints?". Both endpoints get the
     annotation so the entire segment is covered.

  3. **at_depth_m auto-fill.** Each keypoint gets `at_depth_m` sampled
     directly from the depth map at the click pixel. Same value the compositor
     would compute at runtime — embedding it here just makes the trajectory
     self-contained. Remove any value by hand-editing the JSON if the depth
     map is noisy at that spot.

Frame numbers are auto-assigned at a fixed step (default 30, = 1s at 30fps).
Facing is auto-derived from movement direction (left vs right relative to the
previous point). Animation defaults to "hop" or the character's
`default_animation` and is inherited from the previous keypoint until you edit
the output JSON.

Key bindings (matplotlib window must have focus):
    Left-click   add a foot point
    u            undo the last point
    s            save trajectory.json and exit
    q            quit without saving (confirmation in terminal)

Usage:
    python -m src.compositor.trajectory_authoring \\
        --scene-dir output/processed_scene/desk \\
        --output    output/processed_scene/desk/trajectory.json \\
        [--character-ref output/pets/Fluffball/character.json] \\
        [--fps 30] \\
        [--frame-step 30] \\
        [--start-frame 0] \\
        [--default-animation hop]
"""

import argparse
import json
import os
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np


# ──────────────────────────────────────────────
# VISUAL CONSTANTS
# ──────────────────────────────────────────────

# Object-mask outline (is_object=true)
MASK_OUTLINE_COLOR        = "#00ffff"   # cyan
MASK_OUTLINE_LW           = 0.8
MASK_OUTLINE_ALPHA        = 0.75

# Noise-mask outline (is_object=false, e.g. sky)
NOISE_OUTLINE_COLOR       = "#666666"
NOISE_OUTLINE_LW          = 0.5
NOISE_OUTLINE_ALPHA       = 0.3

MASK_LABEL_FONTSIZE       = 7
MASK_LABEL_BG             = dict(boxstyle="round,pad=0.2",
                                  facecolor="black", alpha=0.55,
                                  edgecolor="none")

TRAJ_LINE_COLOR           = "#ffcc00"
TRAJ_LINE_LW              = 2.0
TRAJ_LINE_ALPHA           = 0.85

POINT_COLOR               = "#ff00ff"
POINT_SIZE                = 70
POINT_EDGE                = "black"

POINT_LABEL_FONTSIZE      = 7
POINT_LABEL_BG            = dict(boxstyle="round,pad=0.25",
                                  facecolor="#003366", alpha=0.85,
                                  edgecolor="none")


# ──────────────────────────────────────────────
# AUTHORING TOOL
# ──────────────────────────────────────────────

class TrajectoryAuthor:
    """
    Matplotlib-based interactive authoring tool.

    Visual state lives on the matplotlib axes; semantic state (keypoints)
    lives in `self.keypoints`. The two are kept in sync via `_redraw` which
    is called after every meaningful state change. Click events block on
    terminal `input()` calls for on_top_of resolution — the matplotlib
    window doesn't repaint during a prompt, but it doesn't need to: the
    user is looking at the terminal then.
    """

    def __init__(self, scene_dir, output_path, character_ref=None,
                 fps=30, frame_step=30, start_frame=0,
                 default_animation="hop"):
        self.scene_dir         = Path(scene_dir)
        self.output_path       = Path(output_path)
        self.character_ref     = character_ref
        self.fps               = fps
        self.frame_step        = frame_step
        self.start_frame       = start_frame
        self.default_animation = default_animation

        # scene_ref is stored verbatim into trajectory.json so the
        # compositor can find the scene. Use the same relative form
        # the user passed in on the CLI.
        self.scene_ref = str(self.scene_dir / "scene_processed.json")

        self._load_scene()
        self._load_character()

        # keypoints[i] is a dict mirroring the trajectory format, except
        # on_top_of is always a list internally (cleaned up in _save).
        self.keypoints = []

        self._setup_figure()
        self._print_instructions()

    # ──────────────────────────────────────────
    # LOADING
    # ──────────────────────────────────────────

    def _load_scene(self):
        scene_json = self.scene_dir / "scene_processed.json"
        if not scene_json.exists():
            raise FileNotFoundError(
                f"No scene_processed.json in {self.scene_dir}. "
                f"Run scene_preprocessor + scene_labeler first.")
        with open(scene_json) as f:
            scene_data = json.load(f)

        scene_cfg = scene_data["scene"]
        img_path = scene_cfg["image_path"]
        bgr = cv2.imread(img_path)
        if bgr is None:
            raise FileNotFoundError(
                f"Scene image not found: {img_path}")
        self.bg_image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.h, self.w = self.bg_image.shape[:2]

        # Depth map — used to auto-fill at_depth_m at click time.
        depth_path = (scene_data.get("depth_map_path")
                      or scene_cfg.get("depth_map_path"))
        if depth_path and os.path.exists(depth_path):
            self.depth_m = np.load(depth_path)
            if self.depth_m.shape[:2] != (self.h, self.w):
                self.depth_m = cv2.resize(
                    self.depth_m, (self.w, self.h),
                    interpolation=cv2.INTER_LINEAR)
        else:
            self.depth_m = None
            print("⚠️  No depth map found; at_depth_m will be omitted.")

        # Object masks. Store mask as bool ndarray so intersection
        # tests are cheap.
        self.objects = []
        for obj in scene_data.get("objects", []):
            mp = obj.get("mask_path")
            if not mp or not os.path.exists(mp):
                continue
            m = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
            if m is None:
                continue
            if m.shape[:2] != (self.h, self.w):
                m = cv2.resize(m, (self.w, self.h),
                               interpolation=cv2.INTER_NEAREST)
            self.objects.append({
                "id":            obj["id"],
                "label":         obj.get("label", ""),
                "mask":          m > 128,
                "base_depth_m":  float(obj.get("base_depth_m", 0.0)),
                "is_object":     bool(obj.get("is_object", True)),
            })

        n_real = sum(1 for o in self.objects if o["is_object"])
        n_noise = len(self.objects) - n_real
        print(f"Loaded scene: {self.w}×{self.h}px, "
              f"{n_real} object mask(s), {n_noise} noise mask(s)")

    def _load_character(self):
        """Pull available animation names from character.json if given.

        The tool doesn't (currently) let the user pick animation per
        click — clicks inherit the previous point's animation, with the
        first defaulting to `--default-animation`. Loading the
        character is purely so we can warn if the default animation
        isn't in the library.
        """
        self.available_animations = []
        if not self.character_ref:
            return
        if not os.path.exists(self.character_ref):
            print(f"⚠️  character-ref not found: {self.character_ref}")
            return
        with open(self.character_ref) as f:
            cdata = json.load(f)
        self.available_animations = list(cdata.get("animations", {}).keys())
        if self.available_animations:
            print(f"Character animations: "
                  f"{', '.join(self.available_animations)}")
            if self.default_animation not in self.available_animations:
                fallback = (cdata.get("character", {}).get("default_animation")
                            or self.available_animations[0])
                print(f"  ⚠️  default-animation '{self.default_animation}' "
                      f"not in library; using '{fallback}' instead")
                self.default_animation = fallback

    # ──────────────────────────────────────────
    # FIGURE
    # ──────────────────────────────────────────

    def _setup_figure(self):
        self.fig, self.ax = plt.subplots(figsize=(14, 10))
        self.ax.imshow(self.bg_image)
        self.ax.set_title(
            f"Trajectory Authoring — {self.scene_dir.name}    "
            f"(click to add point   ·   u undo   ·   s save   ·   q quit)")

        # Draw mask outlines + labels.
        for obj in self.objects:
            if obj["is_object"]:
                color, lw, alpha = (MASK_OUTLINE_COLOR,
                                    MASK_OUTLINE_LW,
                                    MASK_OUTLINE_ALPHA)
            else:
                color, lw, alpha = (NOISE_OUTLINE_COLOR,
                                    NOISE_OUTLINE_LW,
                                    NOISE_OUTLINE_ALPHA)
            contours, _ = cv2.findContours(
                obj["mask"].astype(np.uint8) * 255,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            for c in contours:
                if len(c) < 3:
                    continue
                pts = c.reshape(-1, 2)
                # Close the contour so the outline doesn't have a gap
                pts = np.vstack([pts, pts[:1]])
                self.ax.plot(pts[:, 0], pts[:, 1],
                             color=color, lw=lw, alpha=alpha, zorder=2)

            # Label at the mask's median pixel — robust to disconnected
            # components, sits on the mask body rather than centroid
            # outside the mask.
            ys, xs = np.where(obj["mask"])
            if len(xs):
                cx, cy = int(np.median(xs)), int(np.median(ys))
                lbl = obj["id"]
                if obj["label"]:
                    lbl = f"{obj['id']}\n{obj['label']}"
                    if not obj["is_object"]:
                        lbl += " [noise]"
                self.ax.text(cx, cy, lbl,
                             fontsize=MASK_LABEL_FONTSIZE,
                             color="white",
                             ha="center", va="center",
                             bbox=MASK_LABEL_BG, zorder=3)

        # Trajectory artists — created empty, mutated in _redraw so we
        # don't accumulate line objects on every click.
        (self._line_artist,) = self.ax.plot(
            [], [], color=TRAJ_LINE_COLOR,
            lw=TRAJ_LINE_LW, alpha=TRAJ_LINE_ALPHA, zorder=5)
        self._scatter_artist = self.ax.scatter(
            [], [], s=POINT_SIZE,
            c=POINT_COLOR, edgecolors=POINT_EDGE, zorder=6)
        self._point_label_artists = []   # text objects, recreated each redraw

        self.ax.set_xlim(0, self.w)
        self.ax.set_ylim(self.h, 0)   # flip y for image coords
        self.ax.set_aspect("equal")

        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event",    self._on_key)

    def _print_instructions(self):
        print()
        print("=" * 64)
        print("TRAJECTORY AUTHORING")
        print("=" * 64)
        print(f"  Output      : {self.output_path}")
        print(f"  Frame step  : +{self.frame_step} per point "
              f"(starting at frame {self.start_frame})")
        print(f"  fps         : {self.fps}")
        print(f"  Animation   : '{self.default_animation}' "
              f"(inherited until edited in JSON)")
        print("-" * 64)
        print("  Left-click on the scene to add foot points.")
        print("  Keys: u=undo  s=save  q=quit")
        print("=" * 64)
        print()

    # ──────────────────────────────────────────
    # CLICK HANDLING
    # ──────────────────────────────────────────

    def _on_click(self, event):
        if event.inaxes != self.ax:
            return
        if event.button != 1:    # only left-click
            return
        if event.xdata is None or event.ydata is None:
            return

        x = int(round(event.xdata))
        y = int(round(event.ydata))
        if not (0 <= x < self.w and 0 <= y < self.h):
            return

        # Build the new keypoint.
        n = len(self.keypoints)
        frame = self.start_frame + n * self.frame_step

        # Facing: derive from x-direction relative to previous point.
        if self.keypoints:
            prev_x = self.keypoints[-1]["foot_position"][0]
            if x < prev_x - 5:        # small dead zone so vertical
                facing = "left"        # movement doesn't flip facing
            elif x > prev_x + 5:
                facing = "right"
            else:
                facing = self.keypoints[-1]["facing"]
        else:
            facing = "right"

        animation = (self.keypoints[-1]["animation"]
                     if self.keypoints else self.default_animation)

        kp = {
            "frame":         frame,
            "foot_position": [x, y],
            "facing":        facing,
            "animation":     animation,
            "on_top_of":     [],
        }
        if self.depth_m is not None:
            d = float(self.depth_m[y, x])
            if d > 0:
                kp["at_depth_m"] = round(d, 4)

        print(f"\n--- Point {n + 1} at ({x}, {y}), frame {frame} ---")
        if "at_depth_m" in kp:
            print(f"  depth-map sample: {kp['at_depth_m']:.3f}m")

        # ── Point-in-mask check ──
        on_masks = [o for o in self.objects
                    if o["is_object"] and o["mask"][y, x]]
        if on_masks:
            print(f"  Inside {len(on_masks)} object mask(s):")
            for o in on_masks:
                print(f"    [{o['id']}] {o['label']}  "
                      f"(base_depth={o['base_depth_m']:.2f}m)")
            for o in on_masks:
                if self._prompt_yes_no(
                        f"  Set on_top_of for [{o['id']}] "
                        f"'{o['label']}'?"):
                    kp["on_top_of"].append(o["id"])

        # ── Line-crossing check (only when there's a previous point) ──
        if self.keypoints:
            prev = self.keypoints[-1]
            crossed = self._line_crossings(
                prev["foot_position"], kp["foot_position"],
                already_covered=set(prev.get("on_top_of", []))
                                  | set(kp["on_top_of"]),
            )
            if crossed:
                print(f"  Segment {n} → {n + 1} crosses through "
                      f"{len(crossed)} mask(s) neither endpoint is "
                      f"flagged for:")
                for o in crossed:
                    print(f"    [{o['id']}] {o['label']}  "
                          f"(base_depth={o['base_depth_m']:.2f}m)")
                for o in crossed:
                    if self._prompt_yes_no(
                            f"  Add on_top_of for [{o['id']}] "
                            f"'{o['label']}' to BOTH endpoints?"):
                        if o["id"] not in prev["on_top_of"]:
                            prev["on_top_of"].append(o["id"])
                        if o["id"] not in kp["on_top_of"]:
                            kp["on_top_of"].append(o["id"])

        self.keypoints.append(kp)
        self._summarise(kp, n + 1)
        self._redraw()

    def _on_key(self, event):
        if event.key == "u":
            if self.keypoints:
                removed = self.keypoints.pop()
                print(f"\n↶ Undid point {len(self.keypoints) + 1}: "
                      f"frame {removed['frame']}, "
                      f"foot {removed['foot_position']}")
                self._redraw()
            else:
                print("Nothing to undo.")
        elif event.key == "s":
            self._save()
        elif event.key == "q":
            if self.keypoints:
                ok = self._prompt_yes_no(
                    f"\nQuit WITHOUT saving "
                    f"{len(self.keypoints)} keypoint(s)?", default_yes=False)
                if not ok:
                    return
            print("Bye.")
            plt.close(self.fig)

    # ──────────────────────────────────────────
    # INTERSECTION HELPERS
    # ──────────────────────────────────────────

    def _line_crossings(self, p_from, p_to, already_covered):
        """
        Return the list of object dicts whose mask the straight line
        from p_from to p_to passes through, EXCLUDING those already in
        `already_covered`. Uses cv2.line to rasterise the segment into
        a binary buffer and AND-tests against each mask.
        """
        buf = np.zeros((self.h, self.w), dtype=np.uint8)
        cv2.line(buf, (int(p_from[0]), int(p_from[1])),
                       (int(p_to[0]),   int(p_to[1])),
                 255, thickness=1)
        buf_bool = buf > 0
        crossed = []
        for o in self.objects:
            if not o["is_object"]:
                continue
            if o["id"] in already_covered:
                continue
            if np.any(buf_bool & o["mask"]):
                crossed.append(o)
        return crossed

    # ──────────────────────────────────────────
    # USER INTERACTION
    # ──────────────────────────────────────────

    def _prompt_yes_no(self, prompt, default_yes=True):
        suffix = "[Y/n]" if default_yes else "[y/N]"
        while True:
            try:
                ans = input(f"  {prompt} {suffix} ").strip().lower()
            except EOFError:
                # If the terminal closes mid-prompt, fall through to default
                return default_yes
            if ans == "":
                return default_yes
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no"):
                return False
            print("    please answer y or n")

    def _summarise(self, kp, idx):
        otof = kp["on_top_of"]
        otof_s = ", ".join(otof) if otof else "(none)"
        print(f"  → point {idx} added: foot={kp['foot_position']}, "
              f"facing={kp['facing']}, on_top_of={otof_s}")

    # ──────────────────────────────────────────
    # REDRAW
    # ──────────────────────────────────────────

    def _redraw(self):
        # Line + scatter
        if not self.keypoints:
            self._line_artist.set_data([], [])
            self._scatter_artist.set_offsets(np.empty((0, 2)))
        else:
            xs = [k["foot_position"][0] for k in self.keypoints]
            ys = [k["foot_position"][1] for k in self.keypoints]
            self._line_artist.set_data(xs, ys)
            self._scatter_artist.set_offsets(np.column_stack([xs, ys]))

        # Per-point labels (frame + on_top_of summary). Recreate every
        # time — small N, simpler than diffing.
        for t in self._point_label_artists:
            t.remove()
        self._point_label_artists = []
        for i, k in enumerate(self.keypoints):
            x, y = k["foot_position"]
            parts = [f"#{i+1}  f{k['frame']}"]
            if k.get("on_top_of"):
                parts.append("on:" + ",".join(k["on_top_of"]))
            t = self.ax.text(x + 12, y - 12, "\n".join(parts),
                             fontsize=POINT_LABEL_FONTSIZE,
                             color="white",
                             bbox=POINT_LABEL_BG, zorder=7)
            self._point_label_artists.append(t)

        self.fig.canvas.draw_idle()

    # ──────────────────────────────────────────
    # SAVE
    # ──────────────────────────────────────────

    def _save(self):
        if not self.keypoints:
            print("Nothing to save — add at least one point first, "
                  "or press q to quit.")
            return

        out_kps = []
        for k in self.keypoints:
            kp_out = {
                "frame":         k["frame"],
                "foot_position": list(k["foot_position"]),
                "facing":        k["facing"],
                "animation":     k["animation"],
            }
            if "at_depth_m" in k:
                kp_out["at_depth_m"] = k["at_depth_m"]
            # Collapse on_top_of to a string when single, list when
            # multiple, omit when empty. Matches the existing trajectory
            # format the compositor reads.
            otof = k.get("on_top_of") or []
            if len(otof) == 1:
                kp_out["on_top_of"] = otof[0]
            elif len(otof) > 1:
                kp_out["on_top_of"] = otof
            out_kps.append(kp_out)

        trajectory = {
            "scene_ref":     self.scene_ref,
            "fps":           self.fps,
            "_comment": [
                "Authored via trajectory_authoring.py.",
                "Frame numbers were auto-assigned at +"
                f"{self.frame_step} per click; "
                "edit them here for finer timing.",
                "at_depth_m values were sampled from the depth map at "
                "click time; remove a value if you'd rather the "
                "compositor sample at runtime.",
            ],
            "keypoints":     out_kps,
        }
        if self.character_ref:
            # Place character_ref before keypoints so the file reads
            # top-down: refs first, comments, then data.
            trajectory = {
                "scene_ref":     trajectory["scene_ref"],
                "character_ref": self.character_ref,
                "fps":           trajectory["fps"],
                "_comment":      trajectory["_comment"],
                "keypoints":     trajectory["keypoints"],
            }

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w") as f:
            json.dump({"trajectory": trajectory}, f, indent=2)
        print(f"\n✓ Wrote {len(out_kps)} keypoint(s) to "
              f"{self.output_path}")
        plt.close(self.fig)

    # ──────────────────────────────────────────
    # RUN
    # ──────────────────────────────────────────

    def run(self):
        plt.show()


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Manual trajectory authoring with click-to-add "
                    "foot points and automatic on_top_of detection.",
    )
    parser.add_argument(
        "--scene-dir", required=True,
        help="Scene directory containing scene_processed.json "
             "(post scene_labeler).",
    )
    parser.add_argument(
        "--output", required=True,
        help="Where to write the trajectory.json.",
    )
    parser.add_argument(
        "--character-ref", default=None,
        help="Optional character.json. Used only to validate the "
             "default animation name against the character's library.",
    )
    parser.add_argument(
        "--fps", type=int, default=30,
        help="Frames per second written into trajectory.json. "
             "Default 30.",
    )
    parser.add_argument(
        "--frame-step", type=int, default=30,
        help="Frame offset between consecutive auto-assigned keypoints. "
             "Default 30 = 1 second at 30fps.",
    )
    parser.add_argument(
        "--start-frame", type=int, default=0,
        help="Frame number of the first keypoint. Default 0.",
    )
    parser.add_argument(
        "--default-animation", default="hop",
        help="Animation name for the first keypoint. Subsequent "
             "keypoints inherit from the previous one until edited "
             "in the output JSON. Default 'hop'.",
    )
    args = parser.parse_args()

    author = TrajectoryAuthor(
        scene_dir=args.scene_dir,
        output_path=args.output,
        character_ref=args.character_ref,
        fps=args.fps,
        frame_step=args.frame_step,
        start_frame=args.start_frame,
        default_animation=args.default_animation,
    )
    author.run()


if __name__ == "__main__":
    main()