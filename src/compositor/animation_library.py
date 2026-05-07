"""
animation_library.py

Replaces the single-video CharacterContext from the original compositor with
a multi-animation library that mirrors DigitalPet's actual output: one set
of pre-extracted, canvas-centered frames per action.

The library reads from the output of `character_extractor.py`, not the
original GIFs:

    <animations_dir>/extracted/
        canvas.json
        <action>/
            frames/frame_NNNN.png
            masks/frame_NNNN.png

All actions share the same square canvas size (computed by the extractor
as the max bounding box across the whole library, plus padding). This
shared canvas is what makes the foot anchor consistent regardless of
which action is currently playing — switching `hop -> idle -> hop`
doesn't visually shift the character.

Design:

  - All frames are loaded into memory up-front. Each pet's full library
    is small (a dozen actions × ~16 frames × ~300KB each at canvas size),
    so the memory cost is negligible compared to per-frame disk reads.

  - Each action carries an independent playhead. When the trajectory says
    'hop' for several seconds, then 'idle', then back to 'hop', the hop
    cycle resumes from where it left off rather than snapping to frame 0.

  - Frames are returned as (BGR uint8 image, uint8 mask) — the same shape
    the rest of the pipeline expects.
"""

import json
from pathlib import Path
import cv2


class AnimationLibrary:
    """
    Loads a pet's pre-extracted animation library produced by
    `character_extractor.extract_pet`.

    Frames are kept in memory as BGR uint8 numpy arrays so the compositor
    can hand them straight to OpenCV.
    """

    def __init__(self, character_json_path: str):
        with open(character_json_path) as f:
            data = json.load(f)

        cfg = data["character"]
        self.name = cfg.get("name", "pet")

        # The compositor reads from `frames_dir`, which points at the
        # extractor's output. For backward compatibility with older configs
        # that say `animations_dir`, fall back to <animations_dir>/extracted.
        if "frames_dir" in cfg:
            self.frames_dir = Path(cfg["frames_dir"])
        elif "animations_dir" in cfg:
            self.frames_dir = Path(cfg["animations_dir"]) / "extracted"
        else:
            raise KeyError(
                "character.json must specify either 'frames_dir' "
                "(preferred) or 'animations_dir'."
            )

        self.start_frame          = int(cfg.get("start_frame", 0))
        self.foot_offset_x_frac   = float(cfg.get("foot_offset_x_frac", 0.5))
        self.foot_offset_y_frac   = float(cfg.get("foot_offset_y_frac", 0.95))
        self.physical_thickness_m = float(cfg.get("physical_thickness_m", 0.5))

        # Default fallback for missing animations
        self.default_animation = cfg.get("default_animation", "idle")

        # Per-action metadata from character.json (facing, looping)
        self.animations_meta = data.get("animations", {})

        # action -> [(frame_bgr, mask), ...]
        self._library: dict = {}
        # action -> playhead index
        self._playheads: dict = {}

        # Load canvas metadata (written by character_extractor)
        self._canvas_size = self._load_canvas_meta(cfg)

        # native_height_px defaults to canvas size (every frame is square)
        self.native_height_px = int(cfg.get("native_height_px",
                                             self._canvas_size))

        self._load_library()

        if not self._library:
            raise FileNotFoundError(
                f"No actions loaded from {self.frames_dir}. "
                f"Did you run character_extractor.extract_pet first?"
            )

        if self.default_animation not in self._library:
            self.default_animation = sorted(self._library.keys())[0]

        print(f"AnimationLibrary loaded for '{self.name}': "
              f"{len(self._library)} actions "
              f"({', '.join(sorted(self._library.keys()))})")
        print(f"  canvas = {self._canvas_size}×{self._canvas_size}px, "
              f"default action = {self.default_animation}")

    # ──────────────────────────────────────────────
    # LOADING
    # ──────────────────────────────────────────────

    def _load_canvas_meta(self, cfg: dict) -> int:
        """
        Read canvas.json next to the action subdirectories. If it's
        missing, infer the canvas size from the first frame found.
        """
        canvas_json = self.frames_dir / "canvas.json"
        if canvas_json.exists():
            with open(canvas_json) as f:
                meta = json.load(f)
            return int(meta["canvas_size"])

        # Fallback: peek at the first frame to determine canvas size.
        for action_dir in sorted(self.frames_dir.iterdir()):
            frames_subdir = action_dir / "frames"
            if frames_subdir.is_dir():
                first = sorted(frames_subdir.glob("frame_*.png"))
                if first:
                    img = cv2.imread(str(first[0]))
                    if img is not None and img.shape[0] == img.shape[1]:
                        return img.shape[0]
        # Last-ditch — use whatever the user set in character.json
        return int(cfg.get("native_height_px", 256))

    def _load_library(self):
        """
        Walk <frames_dir>/<action>/{frames,masks}/ and load everything
        into memory.
        """
        if not self.frames_dir.is_dir():
            raise FileNotFoundError(
                f"Extracted frames dir not found: {self.frames_dir}. "
                f"Run `python -m src.compositor.character_extractor "
                f"--animations-dir <pet>/animations` first."
            )

        action_dirs = sorted(p for p in self.frames_dir.iterdir() if p.is_dir())

        for action_dir in action_dirs:
            action      = action_dir.name
            frames_dir  = action_dir / "frames"
            masks_dir   = action_dir / "masks"

            if not (frames_dir.is_dir() and masks_dir.is_dir()):
                # Not an action folder (could be e.g. a leftover raw_frames/)
                continue

            frame_paths = sorted(frames_dir.glob("frame_*.png"))
            mask_paths  = sorted(masks_dir.glob("frame_*.png"))

            if not frame_paths:
                continue

            if len(frame_paths) != len(mask_paths):
                print(f"  ⚠️  {action}: {len(frame_paths)} frames vs "
                      f"{len(mask_paths)} masks — skipping")
                continue

            pairs = []
            for fp, mp in zip(frame_paths, mask_paths):
                img  = cv2.imread(str(fp))
                mask = cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE)
                if img is None or mask is None:
                    raise IOError(
                        f"Could not read frame/mask pair: {fp}, {mp}"
                    )
                # Sanity check: frame and mask must agree on size
                if mask.shape[:2] != img.shape[:2]:
                    mask = cv2.resize(mask, (img.shape[1], img.shape[0]),
                                      interpolation=cv2.INTER_NEAREST)
                pairs.append((img, mask))

            self._library[action]   = pairs
            self._playheads[action] = self.start_frame % len(pairs)

    # ──────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────

    def has_action(self, action: str) -> bool:
        return action in self._library

    def actions(self) -> list:
        return sorted(self._library.keys())

    def get_animation_meta(self, action: str) -> dict:
        """Returns character.json's animations[<action>] block, or {}."""
        return self.animations_meta.get(action, {})

    def cycle_length(self, action: str) -> int:
        if action not in self._library:
            action = self.default_animation
        return len(self._library[action])

    @property
    def canvas_size(self) -> int:
        return self._canvas_size

    def step(self, action: str) -> tuple:
        """
        Advance the named action's playhead by one frame and return
        (frame_bgr, mask). If the action isn't in the library, fall back
        to the default action with a one-time warning.
        """
        if action not in self._library:
            warn_attr = f"_warned_{action}"
            if not getattr(self, warn_attr, False):
                print(f"  ⚠️  Action '{action}' not in library, "
                      f"using '{self.default_animation}' instead.")
                setattr(self, warn_attr, True)
            action = self.default_animation

        idx = self._playheads[action]
        frame_bgr, mask = self._library[action][idx]
        self._playheads[action] = (idx + 1) % len(self._library[action])
        return frame_bgr.copy(), mask.copy()

    def reset_playhead(self, action: str = None):
        if action is None:
            for a in self._playheads:
                self._playheads[a] = self.start_frame % len(self._library[a])
        elif action in self._playheads:
            self._playheads[action] = (self.start_frame
                                       % len(self._library[action]))

    def release(self):
        # No file handles to close — kept for API symmetry with the
        # original CharacterContext that wrapped a cv2.VideoCapture.
        pass
