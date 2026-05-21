"""
scene_labeler.py

Adds semantic labels to objects in a preprocessed scene. Runs *after*
`scene_preprocessor.py`. Consumes a `scene_processed.json` and writes
labels back into it in place.

Two-pass design:

  Pass 1 (per-segment, parallel-friendly):
    For each object, crop its bbox region from the scene image and ask
    Gemini Flash to label it. Returns {label, confidence, is_object}.
    Generic labels at this stage — `"mouse"` not `"left mouse"`.

  IoU clustering (deterministic, no VLM):
    Segments sharing the same generic label are grouped by mask IoU.
    Pairs with IoU >= 0.5 are treated as the same physical object and
    keep the shared label. Pairs with IoU < 0.5 are distinct instances.

  Pass 2 (multi-instance disambiguation, sparse):
    For each set of multiple distinct instances sharing a generic label
    (the two-mice case), send one VLM call with full scene context
    asking it to assign distinguishing names. Falls back to numeric
    suffix (`mouse_1`, `mouse_2`) if the VLM doesn't return clean output.

Output: scene_processed.json's `objects[].label` field gets populated.
The trajectory's `on_top_of` can then reference labels and the
compositor will resolve to all segments sharing that label.

Why this two-pass approach:
  - One real object split across SAM2 segments (over-segmentation) gets
    handled by IoU clustering. Free, deterministic, geometrically
    correct.
  - Multiple distinct instances of the same kind of object (two mice)
    need genuine semantic disambiguation, which only the VLM can do —
    but it's only invoked when actually needed.
"""

import os
import json
import argparse
from collections import defaultdict
from io import BytesIO

import cv2
import numpy as np
from PIL import Image


# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────

# Geometric threshold for treating two same-labelled segments as the
# same physical object. 0.5 means at least half of their union must be
# shared — strong enough to merge over-segmented duplicates without
# falsely merging adjacent-but-distinct objects.
IOU_MERGE_THRESHOLD = 0.5

# Geometric threshold for "this small segment is mostly INSIDE that
# larger segment". intersection / smaller_mask_area >= 0.8 means at
# least 80% of the smaller segment lies within the larger.
CONTAINMENT_THRESHOLD = 0.8

# Lower bound on IoU for treating two segments as candidate "alternate
# segmentations of the same physical object" (the over-segmentation
# case). Pairs at or above this IoU but BELOW the containment ratio
# still get sent to the VLM verifier — the verifier decides whether
# they're really the same thing. This catches SAM2 producing two
# slightly-different masks of the same keyboard/mouse that don't
# cleanly fit a parent/child pattern.
ALTERNATE_SEGMENT_IOU_THRESHOLD = 0.4

# If two segments are nearly identical (very high mutual containment),
# they're really an IoU-clustering case, not a containment case. This
# upper bound prevents containment from also firing on those — IoU
# clustering handles them with cleaner semantics.
CONTAINMENT_IOU_SKIP_THRESHOLD = 0.95

# Crop padding (fraction of bbox dimension) around each segment when
# sending to the VLM. Adds context that helps recognition.
CROP_PAD_FRAC = 0.10

# Max edge length for VLM crops — keeps token cost bounded for very
# large segments while preserving recognition detail.
MAX_CROP_EDGE = 512

# Vision model used for both labeling passes
VISION_MODEL = "gemini-2.5-flash"


# ──────────────────────────────────────────────
# CROPPING
# ──────────────────────────────────────────────

def _bbox_crop(scene_image: np.ndarray, obj: dict,
               pad_frac: float = CROP_PAD_FRAC) -> Image.Image:
    """
    Crop the scene image around an object's bbox, with pad_frac padding
    of surrounding context. The segment of interest is OUTLINED inside
    the crop so the VLM knows which region to label — without this,
    the VLM tends to label the most visually prominent object in the
    crop, which is often a neighbor rather than the actual segment.

    Natural surrounding context is otherwise preserved (no masking out
    of pixels outside the mask), because contextual cues like
    surrounding objects, surfaces, and lighting help with recognition.
    """
    h, w = scene_image.shape[:2]
    x1, y1, x2, y2 = obj["x_min"], obj["y_min"], obj["x_max"], obj["y_max"]
    bw, bh = x2 - x1, y2 - y1
    pad = int(max(bw, bh) * pad_frac)

    cx1 = max(0, x1 - pad)
    cy1 = max(0, y1 - pad)
    cx2 = min(w, x2 + pad)
    cy2 = min(h, y2 + pad)

    # Copy the crop region BEFORE drawing, so the outline doesn't
    # bleed into other crops (scene_image is shared across calls).
    crop_bgr = scene_image[cy1:cy2, cx1:cx2].copy()

    # Draw the mask outline so the VLM knows what to label. The mask
    # is in scene coordinates, so slice it the same way as the crop.
    mask = obj.get("mask")
    if mask is not None:
        mask_crop = mask[cy1:cy2, cx1:cx2]
        # Bright magenta outline — distinct from anything natural in
        # the scene, easy for the VLM to recognise as "the region
        # we're asking about"
        contours, _ = cv2.findContours(mask_crop, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(crop_bgr, contours, -1, (255, 0, 255), 3)

    crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)

    # Resize down if very large — token cost scales with image size
    ch, cw = crop_rgb.shape[:2]
    longest = max(ch, cw)
    if longest > MAX_CROP_EDGE:
        scale = MAX_CROP_EDGE / longest
        new_w = int(cw * scale)
        new_h = int(ch * scale)
        crop_rgb = cv2.resize(crop_rgb, (new_w, new_h),
                              interpolation=cv2.INTER_AREA)

    return Image.fromarray(crop_rgb)


def _full_scene_with_highlights(scene_image: np.ndarray,
                                objects: list,
                                colors: list = None) -> Image.Image:
    """
    Produce a full-scene image with the given objects outlined in
    distinct colors. Used in pass 2 for multi-instance disambiguation:
    the VLM sees all the candidate segments at once with visual labels.
    """
    if colors is None:
        # Distinct BGR colors for up to 8 instances; recycles after
        colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0),
                  (0, 255, 255), (255, 0, 255), (255, 255, 0),
                  (128, 0, 255), (255, 128, 0)]

    annotated = scene_image.copy()
    for i, obj in enumerate(objects):
        color = colors[i % len(colors)]
        # Find contour for clean outline rather than filled mask
        contours, _ = cv2.findContours(obj["mask"], cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(annotated, contours, -1, color, 3)
        # Label the segment with a number near the centroid
        ys, xs = np.where(obj["mask"] > 128)
        if len(xs) > 0:
            cx, cy = int(np.median(xs)), int(np.median(ys))
            cv2.circle(annotated, (cx, cy), 12, color, -1)
            cv2.putText(annotated, str(i + 1), (cx - 6, cy + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # Resize for reasonable token cost
    h, w = annotated.shape[:2]
    longest = max(h, w)
    if longest > 1024:
        scale = 1024 / longest
        annotated = cv2.resize(annotated, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)

    annotated_rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
    return Image.fromarray(annotated_rgb)


# ──────────────────────────────────────────────
# VLM CALLS
# ──────────────────────────────────────────────

# Pass 1 prompt: ask for distinguishing labels, not generic categories.
#
# Earlier versions of this prompt encouraged "common names" ("keyboard"
# over "mechanical keyboard") — but that caused failures when scenes
# had multiple keyboard-like things (laptop keyboard, mechanical
# keyboard, trackpad). They'd all get the same generic label and end
# up in the same disambiguation group, where Pass 2 would invent
# bizarre distinguishing names because it didn't have enough info to
# tell them apart.
#
# We now ask for distinguishing detail: visible color, material, kind
# of object. If the VLM mislabels two distinct objects with the same
# specific label (e.g. both "white mechanical keyboard"), IoU
# clustering or Pass 2 will sort it out. But if it lumps everything
# into a generic bucket, recovery is much harder.
#
# The segment is outlined in MAGENTA on the crop so the VLM knows
# which region to label — without this it tends to label the most
# visually prominent thing in the crop, which is often a neighbor
# rather than the actual segment.
LABEL_PROMPT = """You are labeling a segment from a scene image.

The crop shows the segment of interest outlined in MAGENTA (bright
pink). The rest of the crop is surrounding context that may help you
identify the object, but you should label only the magenta-outlined
region, NOT the surrounding objects.

Return ONLY a JSON object with these fields, no other text:
{
  "label": "<short noun phrase, lowercase, 2-4 words, ideally specific
            enough to distinguish this from other similar objects in
            the scene>",
  "confidence": <float 0-1>,
  "is_object": <true if the magenta-outlined region is a discrete
                physical object that could be interacted with; false
                if it's a surface, shadow, gradient, sky, distant
                background, lighting artifact, or noise>
}

Guidance for the label:
- Label only what's inside the magenta outline. If the outline covers
  a piece of sky or distant scenery, label it "sky" or "background"
  with is_object=false — don't be fooled by prominent objects nearby.
- Be specific enough that two visually-different objects don't share
  the same label. "mechanical keyboard" not "keyboard"; "wireless
  mouse" not "mouse"; "tissue box" not "box".
- Include a visible distinguishing feature when natural: color, shape,
  material. E.g. "white mechanical keyboard", "pink portable speaker",
  "patterned tissue box".
- Do NOT include vague positional words ("left", "right", "upper") —
  those will be added later if needed for disambiguation.
- If the magenta outline is on a sub-part of a larger object (e.g.
  just a single key, just the trackpad area of a laptop), label it
  as the larger object ("mechanical keyboard" not "key"; "laptop"
  not "trackpad").
- Use is_object=false aggressively for distant scenery (sky, cityscape,
  bridges, far buildings, mountains, water in the distance), lighting
  effects, surface gradients, or any background-y region. These are
  not interactable objects.
"""


DISAMBIGUATE_PROMPT = """The image shows {n} numbered regions that
were all labeled "{label}" in an earlier pass. Look at where each
region is in the scene and produce a distinguishing name for each.

Use spatial qualifiers (left/right/front/back/upper/lower) or any
other distinguishing visual feature.

Return ONLY a JSON list of {n} strings, one per region in order
(region 1, region 2, ...). Example for 2 mice:
["{label}_left", "{label}_right"]

IMPORTANT: If you can see that one or more of the numbered regions
is NOT actually "{label}" but something else entirely (e.g. the
earlier pass mislabeled a bridge as a tissue box), give that
region a label matching what it actually is, not a variant of
"{label}". Better to fix a wrong label than perpetuate it.

Each name should be a short noun phrase, lowercase, with underscores
instead of spaces.
"""


CONTAINMENT_VERIFY_PROMPT = """The image shows two highlighted regions:
- Region A is outlined in RED, currently labeled "{label_a}"
- Region B is outlined in BLUE, currently labeled "{label_b}"

Region B is geometrically contained inside Region A's bounding box.
We need to decide whether they are the same physical object — either
B is a part/sub-region of A, or B is an alternate segmentation of the
same thing as A.

Answer YES if any of these is true:
- B is a part of A (e.g. a key of a keyboard, the screen of a laptop,
  the trackpad of a laptop)
- B is a surface or region within A (e.g. a sticker on a box)
- A and B are alternate segmentations of the same physical object

Answer NO if:
- A and B are clearly distinct physical objects that just happen to
  overlap in bounding box (e.g. a mouse and a tissue box that share
  bbox space because of perspective)
- The labels are unrelated to each other in a way that suggests
  bbox confusion rather than real containment

Return ONLY a JSON object, no other text:
{{
  "same_object": <true or false>,
  "reason": "<one short sentence>"
}}
"""


def _parse_json_response(text: str) -> dict:
    """
    Parse a JSON object/list out of the VLM's text response. Tolerates
    code fences and leading/trailing prose.
    """
    text = text.strip()
    # Strip ```json ... ``` fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop first and last fence lines
        text = "\n".join(line for line in lines[1:-1]
                          if not line.strip().startswith("```"))
    # Find first { or [ and last } or ]
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj < 0 and start_arr < 0:
        raise ValueError(f"No JSON object/array found in: {text!r}")
    start = (start_obj if start_obj >= 0 else len(text))
    start = min(start, start_arr if start_arr >= 0 else len(text))
    end_obj = text.rfind("}")
    end_arr = text.rfind("]")
    end = max(end_obj, end_arr)
    return json.loads(text[start:end + 1])


def _vlm_label_segment(client, scene_image: np.ndarray, obj: dict) -> dict:
    """
    Pass 1: send a single segment's crop to the VLM and get a label.

    Returns: {"label": str, "confidence": float, "is_object": bool}
    On error returns a fallback dict so the pipeline keeps going.

    Retries on transient API failures (429 rate limit, 503 unavailable)
    with exponential backoff. Wraps in our own try/except so the run
    never fails on a single bad segment — empty label is a recoverable
    state (default-mode re-run will retry empty-labeled objects).
    """
    import time

    crop = _bbox_crop(scene_image, obj)
    max_retries = 3
    last_err = None

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=VISION_MODEL,
                contents=[crop, LABEL_PROMPT],
            )
            # Concatenate all text parts (Gemini sometimes splits)
            text = "".join(
                part.text or "" for part in response.parts
                if hasattr(part, "text")
            )
            parsed = _parse_json_response(text)
            return {
                "label":      str(parsed.get("label", "")).strip().lower(),
                "confidence": float(parsed.get("confidence", 0.5)),
                "is_object":  bool(parsed.get("is_object", True)),
            }
        except Exception as e:
            last_err = e
            # Only retry transient errors. 429 (rate limit) and 503
            # (overloaded) are worth retrying; 4xx parse/auth errors
            # aren't going to fix themselves.
            err_str = str(e)
            transient = ("429" in err_str or "503" in err_str
                         or "UNAVAILABLE" in err_str
                         or "RESOURCE_EXHAUSTED" in err_str)
            if not transient or attempt == max_retries - 1:
                break
            # Exponential backoff: 1s, 2s, 4s
            backoff = 2 ** attempt
            print(f"    ⏳ {obj['id']} transient error (attempt "
                  f"{attempt + 1}/{max_retries}); retrying in {backoff}s")
            time.sleep(backoff)

    print(f"    ⚠️  VLM call failed for {obj['id']}: {last_err}")
    return {"label": "", "confidence": 0.0, "is_object": True}


def _vlm_disambiguate_instances(client, scene_image: np.ndarray,
                                 instances: list, base_label: str) -> list:
    """
    Pass 2: given multiple distinct instances sharing a generic label,
    ask the VLM to produce disambiguated names.

    instances: list of object dicts (each must have its mask loaded)
    base_label: the shared generic label (e.g. "mouse")

    Returns: list of new labels, one per instance, in the same order.
    Falls back to f"{base_label}_{i+1}" on any parse error.
    """
    annotated = _full_scene_with_highlights(scene_image, instances)
    prompt = DISAMBIGUATE_PROMPT.format(n=len(instances), label=base_label)

    try:
        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[annotated, prompt],
        )
        text = "".join(
            part.text or "" for part in response.parts
            if hasattr(part, "text")
        )
        parsed = _parse_json_response(text)
        if not isinstance(parsed, list):
            raise ValueError(f"Expected list, got {type(parsed)}")
        if len(parsed) != len(instances):
            raise ValueError(
                f"Expected {len(instances)} labels, got {len(parsed)}"
            )
        return [str(n).strip().lower().replace(" ", "_") for n in parsed]
    except Exception as e:
        print(f"    ⚠️  Disambiguation failed for '{base_label}' "
              f"({len(instances)} instances): {e}. "
              f"Falling back to numeric suffixes.")
        return [f"{base_label}_{i + 1}" for i in range(len(instances))]


def _vlm_verify_containment(client, scene_image: np.ndarray,
                            obj_a: dict, obj_b: dict) -> bool:
    """
    Pass-1.5: given two objects where B is geometrically inside A's
    bbox, ask the VLM whether they're actually the same physical
    object (parent/child relationship) or coincidental bbox overlap.

    Returns True iff the VLM confirms they're the same physical
    object — and so the containment relationship should drive
    relabeling. Returns False on any kind of failure or NO answer,
    biasing toward NOT merging when uncertain (safer to leave good
    labels alone than to clobber them via a false-positive merge).

    The two regions are highlighted on the FULL scene image — A in
    red and B in blue — so the VLM has full spatial context for the
    decision.
    """
    # Render A and B on the scene with distinct outline colors.
    # Reuses the same outline-drawing helper as disambiguation but
    # with hand-picked colors for the two roles.
    annotated = _full_scene_with_highlights(
        scene_image, [obj_a, obj_b],
        colors=[(0, 0, 255), (255, 0, 0)],   # BGR: red for A, blue for B
    )
    prompt = CONTAINMENT_VERIFY_PROMPT.format(
        label_a=obj_a.get("label", "") or "<unknown>",
        label_b=obj_b.get("label", "") or "<unknown>",
    )

    try:
        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[annotated, prompt],
        )
        text = "".join(
            part.text or "" for part in response.parts
            if hasattr(part, "text")
        )
        parsed = _parse_json_response(text)
        same = bool(parsed.get("same_object", False))
        reason = str(parsed.get("reason", "")).strip()
        result = "✓ SAME" if same else "✗ DIFFERENT"
        print(f"    {result}  {obj_a['id']} '{obj_a.get('label','')}' "
              f"⊃ {obj_b['id']} '{obj_b.get('label','')}'"
              + (f"  ({reason})" if reason else ""))
        return same
    except Exception as e:
        # Conservative on failure: don't apply the relabel/merge.
        # If the VLM call can't decide, leaving the labels alone is
        # safer than auto-merging and getting it wrong.
        print(f"    ⚠️  Containment verification failed for "
              f"{obj_a['id']} ⊃ {obj_b['id']}: {e}. "
              f"Treating as NOT same object.")
        return False


# ──────────────────────────────────────────────
# IoU CLUSTERING
# ──────────────────────────────────────────────

def _mask_iou(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Standard mask IoU using uint8 masks where >128 is foreground."""
    a = mask_a > 128
    b = mask_b > 128
    intersection = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 0.0
    return float(intersection) / float(union)


def _cluster_by_iou(objects: list,
                    threshold: float = IOU_MERGE_THRESHOLD) -> list:
    """
    Cluster objects by mask IoU. Two objects are in the same cluster if
    they have IoU >= threshold (transitively — A merges B, B merges C,
    so A/B/C all cluster).

    Returns: list of clusters, each cluster is a list of object dicts.
    """
    n = len(objects)
    # Union-find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if _mask_iou(objects[i]["mask"], objects[j]["mask"]) >= threshold:
                union(i, j)

    clusters_by_root = defaultdict(list)
    for i in range(n):
        clusters_by_root[find(i)].append(objects[i])
    return list(clusters_by_root.values())


def _mask_containment(small_mask: np.ndarray,
                      large_mask: np.ndarray) -> float:
    """
    Compute "containment" ratio: fraction of the smaller mask's area
    that falls inside the larger mask. Range [0, 1].

    intersection / area(small_mask)

    Asymmetric (unlike IoU): if small is entirely inside large, returns
    1.0 regardless of how big `large` is. This is what we want for
    detecting sub-parts: spacebar mostly inside keyboard returns ~1.0
    even though keyboard is much bigger.
    """
    s = small_mask > 128
    l = large_mask > 128
    small_area = s.sum()
    if small_area == 0:
        return 0.0
    intersection = np.logical_and(s, l).sum()
    return float(intersection) / float(small_area)


def _find_candidate_containment_pairs(objects: list,
                                       threshold: float = CONTAINMENT_THRESHOLD
                                       ) -> list:
    """
    Geometrically detect (small_obj, large_obj) pairs likely to be the
    same physical object. Returns a list of (small_idx, large_idx)
    tuples into `objects`.

    Two relationship patterns qualify:

      1. **Parent/child containment**: small's mask is mostly inside
         large's mask (intersection / small_area >= threshold). Classic
         "spacebar inside keyboard" case.

      2. **Alternate segmentation**: small and large have high IoU
         (>= ALTERNATE_SEGMENT_IOU_THRESHOLD). Catches the case where
         SAM2 produced two slightly-different masks of the same physical
         object that don't cleanly nest — e.g. two overlapping mask
         attempts at the same keyboard. The verifier sorts out whether
         they're really the same thing.

    In both cases the VLM verification step downstream filters this
    geometric candidate list down to only pairs the VLM agrees are
    the same physical object.

    Skipped:
      - Both must have is_object: true and non-empty masks
      - Very high-IoU near-identical pairs (IoU >= CONTAINMENT_IOU_SKIP_
        THRESHOLD = 0.95) — these are duplicates handled by IoU
        clustering downstream
    """
    def _bbox_area(obj):
        return ((obj.get("x_max", 0) - obj.get("x_min", 0))
                * (obj.get("y_max", 0) - obj.get("y_min", 0)))

    pairs = []
    # Order indices by bbox area ascending — for each "small", we
    # consider only larger ones.
    indexed = sorted(range(len(objects)),
                     key=lambda i: _bbox_area(objects[i]))

    for ii, i in enumerate(indexed):
        small = objects[i]
        if not small.get("is_object", True):
            continue
        for j in indexed[ii + 1:]:
            large = objects[j]
            if not large.get("is_object", True):
                continue
            cont = _mask_containment(small["mask"], large["mask"])
            iou = _mask_iou(small["mask"], large["mask"])
            # Skip near-identical pairs (IoU clustering handles those)
            if iou >= CONTAINMENT_IOU_SKIP_THRESHOLD:
                continue
            # Qualify on EITHER strong containment OR meaningful IoU
            qualifies = (cont >= threshold
                         or iou >= ALTERNATE_SEGMENT_IOU_THRESHOLD)
            if not qualifies:
                continue
            pairs.append((i, j))
    return pairs


def _verify_containment_pairs(client, scene_image: np.ndarray,
                              objects: list, pairs: list) -> set:
    """
    Run the VLM verifier on each candidate pair and return the set of
    pairs the VLM confirms are the same physical object.

    Returned set contains (small_id, large_id) string tuples for fast
    membership checks during relabeling and superset detection.

    A NO answer from the verifier (or any error) means the pair is
    rejected — those two objects stay independent. This is the
    conservative choice: we'd rather miss a real containment than
    incorrectly merge two distinct objects.
    """
    verified = set()
    if not pairs:
        return verified

    print(f"\n── Verifying {len(pairs)} containment pair(s) with VLM "
          f"(rejects bbox-overlap false positives)")
    for small_idx, large_idx in pairs:
        small = objects[small_idx]
        large = objects[large_idx]
        # Pass large as A, small as B (per CONTAINMENT_VERIFY_PROMPT
        # convention: A is the container)
        ok = _vlm_verify_containment(client, scene_image, large, small)
        if ok:
            verified.add((small["id"], large["id"]))

    print(f"  → {len(verified)}/{len(pairs)} pair(s) verified as same "
          f"physical object")
    return verified


def _find_superset_ids(objects: list,
                       threshold: float = CONTAINMENT_THRESHOLD,
                       verified_pairs: set = None) -> set:
    """
    Identify segments that are "supersets" — single masks that cover
    MULTIPLE distinctly-labeled smaller segments. Returns the set of
    those large segments' IDs.

    These segments should be EXCLUDED from being used as parent labels
    during containment relabeling, because relabeling their children to
    the superset's label would destroy distinct semantic identities.
    For example, `computer mice` containing both `left_computer_mouse`
    and `right_computer_mouse`: if we relabeled both children to
    `computer mice`, we'd lose the ability to address them separately.

    If `verified_pairs` is provided, only (small_id, large_id) pairs in
    that set count as containment — un-verified pairs are skipped. This
    is the safer mode because it filters out bbox-overlap false
    positives that the VLM verifier rejected.

    Used internally by `_apply_containment_relabeling` and also by
    `_detect_supersets` (which prints warnings about the same set).
    """
    def _bbox_area(obj):
        return ((obj.get("x_max", 0) - obj.get("x_min", 0))
                * (obj.get("y_max", 0) - obj.get("y_min", 0)))

    superset_ids = set()
    for big in objects:
        if not big.get("is_object", True):
            continue
        big_label = big.get("label", "").strip()
        if not big_label:
            continue
        # Collect distinctly-labeled non-empty children
        seen_labels = set()
        for small in objects:
            if small["id"] == big["id"]:
                continue
            if not small.get("is_object", True):
                continue
            # When verified_pairs is given, only consider pairs the VLM
            # confirmed are the same physical object. Pairs that didn't
            # make it past verification are treated as independent
            # objects — they don't make `big` a superset.
            if verified_pairs is not None:
                if (small["id"], big["id"]) not in verified_pairs:
                    continue
            else:
                # Legacy path: geometric containment only
                small_label = small.get("label", "").strip()
                if not small_label or small_label == big_label:
                    continue
                if _bbox_area(small) >= _bbox_area(big):
                    continue
                cont = _mask_containment(small["mask"], big["mask"])
                if cont < threshold:
                    continue
            small_label = small.get("label", "").strip()
            if small_label and small_label != big_label:
                seen_labels.add(small_label)
        if len(seen_labels) >= 2:
            superset_ids.add(big["id"])
    return superset_ids


def _apply_containment_relabeling(objects: list,
                                  threshold: float = CONTAINMENT_THRESHOLD,
                                  verified_pairs: set = None) -> int:
    """
    For each pair of objects (A, B) where A's mask is mostly contained
    in B's mask (containment >= threshold), relabel the smaller
    (contained) one with the larger's label.

    Handles two related cases:

      1. **Sub-part of named object** — SAM2 produces both a parent and
         a child segment at different granularities (spacebar inside
         keyboard, key inside trackpad). The VLM correctly identifies
         them as semantically different ("spacebar" vs
         "external_mechanical_keyboard"), but for trajectory authoring
         we want them treated as the same physical object so that
         `on_top_of: "external_mechanical_keyboard"` forces both
         segments IN_FRONT.

      2. **Rescued failed-VLM child** — if a small segment got an
         empty label from a transient VLM error but lies inside a
         well-labeled larger segment, it inherits the parent's label.
         This recovers more segments than re-running the VLM alone.

    If `verified_pairs` is given (a set of (small_id, large_id) tuples),
    only pairs in that set are considered — geometric containment alone
    is no longer enough. This filters out cases where two distinct
    physical objects happen to overlap in bbox (e.g. a tissue box and a
    speaker that share bbox space due to perspective).

    Skipped cases:
      - Same-label pairs (IoU clustering already handles those)
      - Pairs that are near-duplicates by IoU (IoU clustering handles)
      - Parents with empty labels (nothing useful to inherit)
      - `is_object: false` children (already noise, skip silently)
      - Parents that are themselves "supersets" containing multiple
        distinctly-labeled children (their label is too broad to use
        as a relabel target)

    Mutates objects in place. Returns the number of relabelings applied.
    """
    # Sort by mask area ascending so we always know which is "smaller"
    # in any pair. Use bbox area as a cheap proxy for ordering — the
    # containment test itself uses actual mask area.
    def _bbox_area(obj):
        return ((obj.get("x_max", 0) - obj.get("x_min", 0))
                * (obj.get("y_max", 0) - obj.get("y_min", 0)))
    sorted_objs = sorted(objects, key=_bbox_area)

    # Identify supersets — segments that cover multiple distinct
    # children. These are NOT valid relabel targets: renaming the
    # children to a superset's label would destroy their distinct
    # identities. The user gets warned about supersets separately
    # via _detect_supersets so they can be handled manually.
    superset_ids = _find_superset_ids(objects, threshold=threshold,
                                       verified_pairs=verified_pairs)

    relabels = []  # [(small_id, old_label, new_label), ...]
    for i, small in enumerate(sorted_objs):
        if not small.get("is_object", True):
            continue
        small_label = small.get("label", "").strip()
        # NOTE: we DO process empty-label children — those are
        # candidates for being rescued by inheriting a parent's label.

        for large in sorted_objs[i + 1:]:  # only larger ones
            if not large.get("is_object", True):
                continue
            # Skip superset parents — relabeling here would clobber
            # the child's distinct identity
            if large["id"] in superset_ids:
                continue
            large_label = large.get("label", "").strip()
            # Parent must have a usable label
            if not large_label:
                continue
            # Same labels: IoU clustering will handle this case
            if large_label == small_label:
                continue
            # When verified_pairs is given, the pair must have been
            # confirmed by the VLM verifier. This filters out bbox-
            # overlap false positives where two distinct objects
            # happen to share space.
            if verified_pairs is not None:
                if (small["id"], large["id"]) not in verified_pairs:
                    continue
            else:
                # Legacy path: geometric containment only
                iou = _mask_iou(small["mask"], large["mask"])
                if iou >= CONTAINMENT_IOU_SKIP_THRESHOLD:
                    continue
                cont = _mask_containment(small["mask"], large["mask"])
                if cont < threshold:
                    continue

            relabels.append((small["id"], small_label or "<empty>",
                             large_label))
            small["label"] = large_label
            # Only relabel to the FIRST containing parent we find.
            # Since we walk from smallest to largest, the first
            # match is the smallest containing parent — the most-
            # specific (and therefore "correct") match.
            break

    if relabels:
        print(f"\n── Containment relabeling "
              f"(threshold {threshold}, smaller mostly inside larger):")
        for small_id, old, new in relabels:
            print(f"     {small_id}: '{old}' → '{new}'  "
                  f"(absorbed into parent)")

    return len(relabels)


def _detect_supersets(objects: list,
                      threshold: float = CONTAINMENT_THRESHOLD,
                      verified_pairs: set = None) -> None:
    """
    Detect "superset" segments: one segment whose mask contains MULTIPLE
    distinctly-labeled child segments (e.g. one "computer mice" mask
    containing both the left and right mouse segments).

    Unlike containment relabeling which has a clear single-parent
    answer, supersets are ambiguous — relabeling the superset to the
    left mouse's label would miss the right mouse, and vice versa.
    Auto-merging is risky here, so we just log the issue so the user
    can either:
      - manually relabel the superset to one of its children's labels
      - mark the superset as is_object: false
      - add the superset's label as an extra ref in the trajectory

    If `verified_pairs` is given (a set of (small_id, large_id) tuples),
    only VLM-verified containment relationships count. This filters out
    bbox-overlap false positives — e.g. a mouse whose bbox happens to
    contain a tissue box that's separate from it doesn't generate a
    false "superset" warning anymore.

    Does not mutate.
    """
    def _bbox_area(obj):
        return ((obj.get("x_max", 0) - obj.get("x_min", 0))
                * (obj.get("y_max", 0) - obj.get("y_min", 0)))
    sorted_objs = sorted(objects, key=_bbox_area, reverse=True)  # largest first

    warnings = []  # [(big_id, big_label, [(small_id, small_label), ...]), ...]
    for big in sorted_objs:
        if not big.get("is_object", True):
            continue
        big_label = big.get("label", "").strip()
        if not big_label:
            continue

        # Look for distinctly-labeled smaller segments contained in big
        contained = []
        seen_labels = set()
        for small in objects:
            if small["id"] == big["id"]:
                continue
            if not small.get("is_object", True):
                continue
            small_label = small.get("label", "").strip()
            if not small_label or small_label == big_label:
                continue
            # When verified_pairs is given, only verified relationships
            # count as real containment.
            if verified_pairs is not None:
                if (small["id"], big["id"]) not in verified_pairs:
                    continue
            else:
                # Smaller than big?
                if _bbox_area(small) >= _bbox_area(big):
                    continue
                cont = _mask_containment(small["mask"], big["mask"])
                if cont < threshold:
                    continue
            contained.append((small["id"], small_label))
            seen_labels.add(small_label)

        # Only flag as superset if multiple DISTINCT child labels
        if len(seen_labels) >= 2:
            warnings.append((big["id"], big_label, contained))

    if warnings:
        print(f"\n── ⚠️  Detected {len(warnings)} superset segment(s) "
              f"(one mask covers multiple distinctly-labeled objects):")
        for big_id, big_label, contained in warnings:
            print(f"     {big_id} '{big_label}' contains:")
            for s_id, s_label in contained:
                print(f"        - {s_id} '{s_label}'")
            print(f"     → Auto-merging not safe; consider either "
                  f"renaming '{big_label}' to one of the children's "
                  f"labels, marking it is_object=false, or adding its "
                  f"label as an extra ref in trajectory keypoints.")


# ──────────────────────────────────────────────
# MASK DEDUPLICATION
# ──────────────────────────────────────────────
#
# Problem: SAM2 produces multiple overlapping masks for the same
# physical object (full keyboard + keycap region + spacebar; "both
# mice" wide mask + individual left/right mouse masks; etc). Downstream
# labeling, containment relabeling, and disambiguation all try to cope
# with this but consistently produce edge cases that occlude the
# bunny against alternate segmentations of objects it's supposed to
# be on top of.
#
# Solution: BEFORE labeling, fold each cluster of overlapping masks
# down to one mask per physical object. The VLM sees the candidates
# outlined on the full scene and decides:
#   (a) how many distinct physical objects these masks cover, and
#   (b) which single mask best represents each object.
#
# Surplus masks are recorded in a top-level `redundant_masks` list in
# the JSON so the compositor can skip them without losing the data
# for debugging. The objects themselves stay in `objects[]` with
# their full metadata.

# Lower IoU bound for treating two segments as overlapping enough to
# be in the same dedup cluster. Lower than the dedup-disabled labeler's
# IoU threshold because the dedup step is the SAFETY NET — we'd rather
# group too liberally and let the VLM split a too-big cluster than
# miss a real over-segmentation.
DEDUP_GROUP_IOU_THRESHOLD = 0.3

# Containment threshold for dedup grouping. Lower than the relabeling
# threshold for the same reason — be liberal in grouping, then let
# the VLM sort it out.
DEDUP_GROUP_CONTAINMENT_THRESHOLD = 0.7

# Pairs of masks within a single cluster whose IoU meets or exceeds
# this threshold are treated as near-duplicates and collapsed
# deterministically — the larger of the two wins, the smaller is
# dropped without consulting the VLM. This handles a specific
# rendering pathology: when N masks have near-identical coverage,
# only the last-drawn mask is actually visible in the dedup view
# (the alpha-blended fills overpaint each other). The VLM literally
# cannot see the earlier masks and hallucinates descriptions for
# their numbers. Pre-collapsing those pairs upstream means the VLM
# only sees masks that look genuinely different. 0.85 is high enough
# that genuine sub-parts (a spacebar inside a keyboard) don't qualify
# but alternate segmentations of the same object do.
NEAR_DUPLICATE_IOU_THRESHOLD = 0.85


DEDUP_PROMPT = """The image is a cropped region of a larger scene.
Inside the crop, {n} candidate masks are highlighted in distinct
translucent colors and labeled with numbers 1 through {n}. Everything
OUTSIDE these masks has been darkened so you can focus on just the
highlighted regions.

The candidate masks were produced by automatic image segmentation and
they overlap each other. Your job: figure out how many distinct
physical objects these masks cover, and for each object pick the
single mask whose outline best traces just that object.

Look ONLY at the highlighted regions. Do NOT label objects that are
visible in the darkened background — those are not what's being asked
about. Each candidate is identified by its NUMBER, not by its color.

Return ONLY this JSON object, no other text:
{{
  "objects": [
    {{
      "member_masks": <list of mask numbers that segment this object>,
      "best_mask": <single mask number whose outline most cleanly
                    traces just this object>,
      "description": "<2-4 word noun phrase for the object>"
    }},
    ...
  ]
}}

Guidance:
- If all {n} masks are overlapping segmentations of ONE physical
  object (e.g. multiple attempts at the same keyboard), return ONE
  entry with all numbers 1..{n} in member_masks.
- If the masks cover multiple distinct objects whose bounding boxes
  happen to overlap (e.g. two mice side by side), return one entry
  per object, putting each mask in the object it belongs to.
- A "superset" mask covers multiple objects at once. Include it in
  member_masks for every object it covers, but do NOT pick it as
  best_mask — prefer the per-object masks.
- best_mask: the mask whose outline most cleanly traces just the
  object, without including neighbors or excluding parts of the
  object. If two candidates are similar, prefer the slightly larger
  one if it's still mostly on-target — small masks miss the body
  edges which causes occlusion bugs downstream.
- description: short noun phrase for human review only.
- Every mask number from 1 to {n} must appear in member_masks of at
  least one object. If a mask seems wrong/garbage, still place it
  with whatever object it most overlaps with.
"""


def _connected_components(n_nodes: int, edges: list) -> list:
    """
    Union-find based connected components.

    Given n_nodes and a list of (i, j) edges (indices into 0..n_nodes-1),
    return a list of components where each component is a list of node
    indices. Singleton components (no edges) are included.
    """
    parent = list(range(n_nodes))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, j in edges:
        union(i, j)

    groups = {}
    for i in range(n_nodes):
        r = find(i)
        groups.setdefault(r, []).append(i)
    return list(groups.values())


def _find_dedup_clusters(objects: list) -> list:
    """
    Group overlapping masks into clusters. Returns a list of clusters,
    each cluster being a list of indices into `objects`.

    Two masks are in the same cluster if they have either:
      - IoU >= DEDUP_GROUP_IOU_THRESHOLD (≥ 0.3), OR
      - containment ratio (intersection / smaller_area)
        >= DEDUP_GROUP_CONTAINMENT_THRESHOLD (≥ 0.7)

    Note: lower thresholds than the labeler's containment/IoU steps —
    dedup is the safety net; we'd rather over-group and let the VLM
    split a cluster than miss real over-segmentation.

    Clusters of size 1 (no overlapping neighbors) are still returned
    in the result so the caller can decide what to skip.
    """
    n = len(objects)
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            iou = _mask_iou(objects[i]["mask"], objects[j]["mask"])
            if iou >= DEDUP_GROUP_IOU_THRESHOLD:
                edges.append((i, j))
                continue
            # Try containment in either direction. The smaller mask's
            # area is the denominator, so try both orderings.
            a_in_b = _mask_containment(objects[i]["mask"],
                                        objects[j]["mask"])
            b_in_a = _mask_containment(objects[j]["mask"],
                                        objects[i]["mask"])
            if max(a_in_b, b_in_a) >= DEDUP_GROUP_CONTAINMENT_THRESHOLD:
                edges.append((i, j))
    return _connected_components(n, edges)


def _cluster_view_for_dedup(scene_image: np.ndarray,
                             objects: list,
                             bbox_pad: int = 40) -> Image.Image:
    """
    Render a focused view of a dedup cluster, designed to make the
    VLM look at the candidate masks and not get distracted by the
    rest of the scene.

    Pipeline:
      1. Compute the union bbox of all candidate masks; crop the scene
         to that bbox + padding.
      2. Outside any candidate mask, darken pixels to ~30% brightness
         and slightly desaturate. Inside any candidate mask, keep
         normal brightness.
      3. Tint each mask with a distinct translucent color fill.
      4. Outline each mask + draw a large numbered label.

    The end result is a tightly-cropped image where the candidate
    masks are obvious blobs of color against a dimmed background,
    with bold numbers identifying each. The VLM is shown a much more
    constrained question: "what are THESE highlighted things?"

    Why this form: the previous version sent the full scene with thin
    colored outlines, and the VLM consistently identified other objects
    elsewhere in the image rather than what was inside the outlines.
    The crop + darkening removes the distracting context; the
    translucent fill makes the candidate regions visually dominant.
    """
    h, w = scene_image.shape[:2]

    # Combined bbox of all masks in the cluster
    x_mins = [o["x_min"] for o in objects]
    y_mins = [o["y_min"] for o in objects]
    x_maxs = [o["x_max"] for o in objects]
    y_maxs = [o["y_max"] for o in objects]
    cx1 = max(0, min(x_mins) - bbox_pad)
    cy1 = max(0, min(y_mins) - bbox_pad)
    cx2 = min(w, max(x_maxs) + bbox_pad)
    cy2 = min(h, max(y_maxs) + bbox_pad)

    crop = scene_image[cy1:cy2, cx1:cx2].copy()
    crop_h, crop_w = crop.shape[:2]

    # Build the "any mask" union (uint8 0/255) cropped to view
    union_mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
    cropped_masks = []  # per-object mask in crop coords
    for obj in objects:
        m = obj["mask"][cy1:cy2, cx1:cx2]
        cropped_masks.append(m)
        union_mask = np.maximum(union_mask, m)

    # Darken everything outside the union_mask. Convert to HSV, scale V
    # down by 0.30, then back to BGR. Done on the whole crop so the
    # outside is uniformly dim.
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv_dim = hsv.copy()
    hsv_dim[..., 2] *= 0.30
    hsv_dim[..., 1] *= 0.60  # also desaturate slightly
    dimmed = cv2.cvtColor(hsv_dim.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # Composite: keep original pixels where union_mask is set,
    # use dimmed pixels everywhere else.
    union_3 = (union_mask[..., None] > 128).astype(np.uint8)
    composed = crop * union_3 + dimmed * (1 - union_3)
    composed = composed.astype(np.uint8)

    # Translucent color fills per mask (alpha-blended with composed)
    # so each candidate has an obvious distinct color.
    colors = [(0, 0, 255), (0, 255, 0), (255, 0, 0),
              (0, 255, 255), (255, 0, 255), (255, 255, 0),
              (128, 0, 255), (255, 128, 0),
              (0, 128, 255), (128, 255, 0),
              (255, 0, 128), (0, 255, 128)]
    alpha = 0.35  # fill strength
    for i, m in enumerate(cropped_masks):
        color = colors[i % len(colors)]
        color_layer = np.full_like(composed, color)
        m_bool = (m > 128).astype(np.float32)[..., None]
        composed = (composed * (1 - m_bool * alpha)
                    + color_layer * (m_bool * alpha)).astype(np.uint8)

    # Outlines on top so each mask's boundary is sharp
    for i, m in enumerate(cropped_masks):
        color = colors[i % len(colors)]
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(composed, contours, -1, color, 4)

    # Large numbered label at the centroid of each mask. Centroid
    # placement keeps the number on the actual mask (top-left of bbox
    # might fall outside if the mask is L-shaped).
    for i, m in enumerate(cropped_masks):
        color = colors[i % len(colors)]
        # Centroid via moments
        M = cv2.moments(m)
        if M["m00"] == 0:
            # Fall back to bbox top-left
            cx = max(0, objects[i]["x_min"] - cx1 + 8)
            cy = max(30, objects[i]["y_min"] - cy1 + 30)
        else:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        label = str(i + 1)
        # Black halo for legibility against any background
        cv2.putText(composed, label, (cx - 12, cy + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 8,
                    cv2.LINE_AA)
        cv2.putText(composed, label, (cx - 12, cy + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3,
                    cv2.LINE_AA)

    composed_rgb = cv2.cvtColor(composed, cv2.COLOR_BGR2RGB)
    return Image.fromarray(composed_rgb)


def _collapse_near_duplicates(cluster_objs: list,
                               iou_threshold: float
                                   = NEAR_DUPLICATE_IOU_THRESHOLD
                               ) -> tuple:
    """
    Within a single dedup cluster, find pairs of masks whose IoU meets
    or exceeds `iou_threshold` and treat them as alternate segmentations
    of the same physical object. The larger mask in each group wins;
    the rest are dropped.

    Why this matters: in `_cluster_view_for_dedup` the masks are drawn
    one after another with translucent alpha-blended fills. When two
    masks have near-identical coverage, the second-drawn mask overpaints
    the first almost completely, so the first mask is functionally
    invisible to the VLM. The VLM then sees its number floating with
    no highlight and hallucinates a description from whatever it can
    find. Collapsing these pairs before rendering removes the
    pathological inputs entirely.

    Returns (kept, dropped) where:
      - kept: subset of `cluster_objs` (the per-group winners plus all
        objects that had no near-duplicate)
      - dropped: list of {"id", "best_of"} dicts recording who absorbed
        each dropped mask. Format matches the redundant_records used
        elsewhere in dedup so the caller can extend its list directly.

    IoU not containment: a pure containment test would also catch
    parent/child pairs (spacebar mostly inside keyboard) which we
    explicitly DO NOT want to collapse — those are different physical
    things and the VLM is the right judge for them. IoU stays high
    only for masks that are *nearly the same shape and size*, which
    is exactly the alternate-segmentation case.
    """
    n = len(cluster_objs)
    if n <= 1:
        return list(cluster_objs), []

    # Union-find over the cluster
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            iou = _mask_iou(cluster_objs[i]["mask"],
                            cluster_objs[j]["mask"])
            if iou >= iou_threshold:
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    kept = []
    dropped = []
    # Walk in original order so kept[] preserves the input ordering
    # (a small thing, but it makes log output stable).
    handled = set()
    for i in range(n):
        if i in handled:
            continue
        group = groups[find(i)]
        handled.update(group)
        if len(group) == 1:
            kept.append(cluster_objs[i])
            continue
        # Pick the largest mask (by pixel area) as the survivor.
        # Bigger masks tend to be the more complete segmentations —
        # smaller ones often miss edges.
        winner = max(
            group,
            key=lambda idx: int((cluster_objs[idx]["mask"] > 128).sum()),
        )
        kept.append(cluster_objs[winner])
        for idx in group:
            if idx == winner:
                continue
            dropped.append({
                "id": cluster_objs[idx]["id"],
                "best_of": cluster_objs[winner]["id"],
            })

    return kept, dropped


def _vlm_dedup_cluster(client, scene_image: np.ndarray,
                       cluster_objects: list,
                       debug_dir: str = None,
                       cluster_index: int = None) -> list:
    """
    Send one VLM call asking it to group the given overlapping masks
    by physical object and pick one best mask per object.

    Returns a list of dicts:
      [{"member_indices": [int, ...], "best_index": int,
        "description": str}, ...]

    Indices are into `cluster_objects` (0-based). On failure, returns
    a single group containing all masks with the largest one as best —
    conservative fallback that keeps one of the masks rather than
    dropping everything.

    Debug dumping:
      If `debug_dir` is provided (and `cluster_index` set), the rendered
      cluster view is saved as `cluster_NN_<ids>.png` and a sidecar
      `cluster_NN_<ids>.json` captures the prompt, raw VLM response,
      any error, and the parsed groups. The image is saved BEFORE the
      VLM call so it survives even if the call hangs or crashes; the
      sidecar is written after with the outcome.
    """
    n = len(cluster_objects)
    annotated = _cluster_view_for_dedup(scene_image, cluster_objects)
    prompt = DEDUP_PROMPT.format(n=n)

    # Pre-save the rendered image so we always have something to inspect.
    debug_image_path = None
    debug_json_path = None
    if debug_dir is not None and cluster_index is not None:
        os.makedirs(debug_dir, exist_ok=True)
        ids_part = "_".join(o["id"] for o in cluster_objects)
        # Cap filename length — very large clusters can produce
        # unreasonably long names otherwise.
        if len(ids_part) > 100:
            ids_part = ids_part[:90] + f"_and_more_{n}"
        stem = f"cluster_{cluster_index:02d}_{ids_part}"
        debug_image_path = os.path.join(debug_dir, f"{stem}.png")
        debug_json_path = os.path.join(debug_dir, f"{stem}.json")
        try:
            annotated.save(debug_image_path)
        except Exception as e:
            print(f"    ⚠️  Could not save debug image "
                  f"{debug_image_path}: {e}")
            debug_image_path = None

    raw_text = ""
    error_msg = None
    result = []

    try:
        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[annotated, prompt],
        )
        raw_text = "".join(
            part.text or "" for part in response.parts
            if hasattr(part, "text")
        )
        parsed = _parse_json_response(raw_text)
        raw_objects = parsed.get("objects", [])
        if not isinstance(raw_objects, list) or not raw_objects:
            raise ValueError("VLM returned no objects")

        for entry in raw_objects:
            members = entry.get("member_masks", [])
            best = entry.get("best_mask")
            desc = str(entry.get("description", "")).strip()
            # Convert 1-indexed → 0-indexed, drop out-of-range entries
            member_idx = [int(m) - 1 for m in members
                          if isinstance(m, (int, float))
                          and 1 <= int(m) <= n]
            if not member_idx:
                continue
            try:
                best_idx = int(best) - 1
                if not (0 <= best_idx < n):
                    raise ValueError
            except (TypeError, ValueError):
                # No valid best_mask — pick the largest member as best
                best_idx = max(
                    member_idx,
                    key=lambda i: int(cluster_objects[i]["mask"].sum())
                )
            # Best mask must be a member; if VLM disagreed with itself,
            # fall back to "biggest member"
            if best_idx not in member_idx:
                best_idx = max(
                    member_idx,
                    key=lambda i: int(cluster_objects[i]["mask"].sum())
                )
            result.append({
                "member_indices": member_idx,
                "best_index": best_idx,
                "description": desc,
            })

        if not result:
            raise ValueError("No valid object groups in VLM response")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"    ⚠️  Dedup VLM call failed: {e}. "
              f"Falling back to 'keep largest, drop rest'.")
        # Conservative fallback: treat the whole cluster as one object,
        # pick the mask with the largest area as best
        biggest = max(range(n),
                      key=lambda i: int(cluster_objects[i]["mask"].sum()))
        result = [{
            "member_indices": list(range(n)),
            "best_index": biggest,
            "description": "<fallback: largest mask in cluster>",
        }]

    # Write the sidecar after the VLM call so it captures the outcome.
    if debug_json_path is not None:
        sidecar = {
            "cluster_index": cluster_index,
            "image_file": (os.path.basename(debug_image_path)
                            if debug_image_path else None),
            "n_masks": n,
            "input_masks": [
                {
                    "local_index_1based": i + 1,
                    "id": o["id"],
                    "x_min": int(o.get("x_min", 0)),
                    "y_min": int(o.get("y_min", 0)),
                    "x_max": int(o.get("x_max", 0)),
                    "y_max": int(o.get("y_max", 0)),
                    "mask_area_px": int((o["mask"] > 128).sum()),
                }
                for i, o in enumerate(cluster_objects)
            ],
            "prompt": prompt,
            "vlm_raw_response": raw_text,
            "vlm_error": error_msg,
            "parsed_groups": [
                {
                    "member_local_indices_1based":
                        [i + 1 for i in g["member_indices"]],
                    "member_ids":
                        [cluster_objects[i]["id"]
                         for i in g["member_indices"]],
                    "best_local_index_1based": g["best_index"] + 1,
                    "best_id":
                        cluster_objects[g["best_index"]]["id"],
                    "description": g["description"],
                }
                for g in result
            ],
        }
        try:
            with open(debug_json_path, "w") as f:
                json.dump(sidecar, f, indent=2)
        except Exception as e:
            print(f"    ⚠️  Could not save debug sidecar "
                  f"{debug_json_path}: {e}")

    return result


def deduplicate_masks(client, scene_image: np.ndarray,
                      objects: list,
                      debug_dir: str = None) -> tuple:
    """
    Group overlapping masks, ask the VLM to pick the best mask per
    physical object, and partition the result into:
      - kept: masks that best represent some physical object
      - redundant: masks that overlap with kept ones (same object)

    Singletons (no overlapping neighbors) are always kept.

    Returns (kept_objects, redundant_ids) where:
      - kept_objects is a list of dicts (subset of `objects`)
      - redundant_ids is a list of {"id", "best_of"} dicts noting which
        kept mask each redundant one was grouped under (for the JSON's
        redundant_masks field)

    If `debug_dir` is provided, each multi-mask cluster's rendered
    VLM-input image and a sidecar JSON with the raw VLM response are
    written there. Singletons are not dumped (no VLM call is made for
    them). Cluster index in filenames matches the print order of
    multi-mask clusters above (singletons don't increment the counter).

    Mutates nothing; caller decides how to record the partition.
    """
    if not objects:
        return [], []

    clusters = _find_dedup_clusters(objects)
    n_clusters = len(clusters)
    n_singletons = sum(1 for c in clusters if len(c) == 1)
    n_multi = n_clusters - n_singletons
    print(f"\n── Mask deduplication: {len(objects)} mask(s) → "
          f"{n_clusters} cluster(s) ({n_singletons} singleton, "
          f"{n_multi} multi)")
    if debug_dir is not None and n_multi > 0:
        print(f"  Dumping per-cluster debug views to {debug_dir}/")

    kept = []
    redundant = []  # list of {"id", "best_of", "in_cluster_with"}

    multi_cluster_idx = 0  # only counts multi-mask clusters

    for cluster_indices in clusters:
        if len(cluster_indices) == 1:
            # Singleton — keep as-is
            kept.append(objects[cluster_indices[0]])
            continue

        multi_cluster_idx += 1
        cluster_objs = [objects[i] for i in cluster_indices]
        ids = [o["id"] for o in cluster_objs]
        print(f"  Cluster of {len(cluster_objs)}: {ids}")

        # ── Geometric pre-collapse ─────────────────────────────────
        # Fold near-duplicate masks (IoU ≥ NEAR_DUPLICATE_IOU_THRESHOLD)
        # together without consulting the VLM. The largest mask in each
        # near-duplicate group wins; the rest are recorded as redundant.
        # This avoids a known rendering pathology: alpha-blended fills
        # for masks with the same coverage overpaint each other and
        # only the last-drawn one is visible to the VLM. Removing the
        # invisible ones up front means the VLM only sees masks that
        # look genuinely different.
        pre_collapsed, pre_dropped = _collapse_near_duplicates(cluster_objs)
        if pre_dropped:
            print(f"    Pre-collapsed {len(pre_dropped)} near-duplicate"
                  f"(s) without VLM (IoU ≥ "
                  f"{NEAR_DUPLICATE_IOU_THRESHOLD}):")
            for r in pre_dropped:
                print(f"      {r['id']} → folded into {r['best_of']}")
            redundant.extend(pre_dropped)
            cluster_objs = pre_collapsed

            # If pre-collapse left a single mask, no VLM call needed.
            if len(cluster_objs) == 1:
                kept.append(cluster_objs[0])
                continue

        # ── VLM dedup on the (possibly pre-collapsed) cluster ──────
        groups = _vlm_dedup_cluster(
            client, scene_image, cluster_objs,
            debug_dir=debug_dir,
            cluster_index=multi_cluster_idx,
        )

        # Local indices in `groups` refer to positions in `cluster_objs`
        # (which may differ from the original cluster after
        # pre-collapse). Build a local-index → object-id map for the
        # logging and bookkeeping below.
        local_to_id = [o["id"] for o in cluster_objs]

        # Which cluster-local indices are "best" for some object?
        best_local_indices = {g["best_index"] for g in groups}

        # Map each cluster-local index to its group's best
        local_to_best = {}
        for g in groups:
            for m in g["member_indices"]:
                local_to_best[m] = g["best_index"]

        for g in groups:
            best_id = local_to_id[g["best_index"]]
            member_ids = [local_to_id[m] for m in g["member_indices"]]
            print(f"    → '{g['description']}': kept {best_id} "
                  f"(from {member_ids})")

        # Walk the (possibly pre-collapsed) cluster in order to keep
        # the output deterministic.
        for local_idx, obj in enumerate(cluster_objs):
            if local_idx in best_local_indices:
                kept.append(obj)
            else:
                # Find which "best" this got grouped under (if any)
                best_local = local_to_best.get(local_idx)
                if best_local is None:
                    # VLM didn't include this mask in any group —
                    # keep it conservatively rather than dropping
                    print(f"    ⚠️  {obj['id']} not assigned to any "
                          f"group by VLM; keeping it as-is")
                    kept.append(obj)
                else:
                    best_id = local_to_id[best_local]
                    redundant.append({
                        "id": obj["id"],
                        "best_of": best_id,
                    })

    print(f"  → Kept {len(kept)} mask(s), marked {len(redundant)} as "
          f"redundant")
    return kept, redundant


# ──────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────

def label_scene(scene_dir: str, force_relabel: bool = False,
                dedupe_masks: bool = True,
                debug_dedup_views: bool = False) -> None:
    """
    Read scene_processed.json from `scene_dir`, optionally deduplicate
    overlapping masks via the VLM, label every remaining object, cluster
    duplicates, disambiguate multi-instance groups, and write back to
    scene_processed.json in place.

    Pipeline:
      1. (optional) Mask deduplication — VLM picks one mask per physical
         object, redundant ones get recorded but excluded from labeling.
         Disable with dedupe_masks=False.
      2. Pass 1 per-segment labeling.
      3. Containment verification + relabeling.
      4. IoU clustering + Pass 2 disambiguation.

    By default, objects that already have a non-empty `label` are
    skipped (preserves manual corrections across re-runs). Pass
    `force_relabel=True` to overwrite.

    If `debug_dedup_views=True` (and dedup is enabled), each multi-mask
    dedup cluster gets its rendered VLM-input image and a sidecar JSON
    of the raw response dumped into <scene_dir>/debug_dedup/. Useful
    for diagnosing why a particular cluster was or wasn't merged.
    """
    # Lazy imports so the rest of the package works without google-genai
    from google import genai

    # Reach into project config for the API key. The compositor package
    # is normally invoked from the project root, so this import works
    # when running as `python -m src.compositor.scene_labeler`.
    try:
        from .. import config  # type: ignore
        api_key = getattr(config, "GEMINI_API_KEY", None)
    except ImportError:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not found. Set it via the project's config "
            "module or as an environment variable."
        )

    scene_dir = os.path.abspath(scene_dir)
    json_path = os.path.join(scene_dir, "scene_processed.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"No scene_processed.json in {scene_dir}")

    with open(json_path) as f:
        scene_data = json.load(f)

    # Load scene image
    image_path = scene_data["scene"]["image_path"]
    scene_image = cv2.imread(image_path)
    if scene_image is None:
        raise FileNotFoundError(f"Could not read scene image: {image_path}")
    print(f"Loaded scene: {image_path} ({scene_image.shape[1]}×"
          f"{scene_image.shape[0]})")

    # Load each object's mask so we have it in memory for IoU clustering
    print(f"Loading masks for {len(scene_data['objects'])} objects...")
    objects_with_masks = []
    for obj in scene_data["objects"]:
        mp = obj.get("mask_path")
        if not mp or not os.path.exists(mp):
            print(f"  ⚠️  Skipping {obj['id']}: mask file missing")
            continue
        mask = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            print(f"  ⚠️  Skipping {obj['id']}: mask unreadable")
            continue
        # Mutate in place — we'll write back to scene_data["objects"]
        obj["mask"] = mask
        objects_with_masks.append(obj)

    client = genai.Client(api_key=api_key)

    # ── (Optional) Mask deduplication ──
    # When SAM2 over-segments — full keyboard + keycap region + spacebar
    # all overlapping — Pass 1 sees them as separate objects and labels
    # them separately. Downstream containment/IoU/disambiguation tries
    # to merge them but produces inconsistent results, leading to
    # occlusion bugs.
    #
    # Dedup fixes this at the source: VLM looks at each cluster of
    # overlapping masks, picks one mask per physical object, marks
    # the rest as "redundant". The labeler then runs only on the
    # representative masks. Redundant IDs are recorded in the
    # top-level `redundant_masks` field so the compositor can skip
    # them and so we preserve the raw data for inspection.
    redundant_records = []
    if dedupe_masks:
        debug_dir = None
        if debug_dedup_views:
            debug_dir = os.path.join(scene_dir, "debug_dedup")
        kept, redundant_records = deduplicate_masks(
            client, scene_image, objects_with_masks,
            debug_dir=debug_dir,
        )
        kept_ids = {o["id"] for o in kept}
        # IMPORTANT: rebuild objects_with_masks to point at the SAME
        # dict objects that are in scene_data["objects"] — so when we
        # mutate label/is_object below, those mutations land in the
        # written JSON. (deduplicate_masks already returns those same
        # dicts; we just need the filtered list.)
        objects_with_masks = [o for o in objects_with_masks
                              if o["id"] in kept_ids]

    # ── Pass 1: per-segment generic labels ──
    print(f"\n── Pass 1: labeling {len(objects_with_masks)} segments")

    to_label = []
    for obj in objects_with_masks:
        existing = obj.get("label", "").strip()
        if existing and not force_relabel:
            print(f"  [{obj['id']}]  '{existing}' (kept; "
                  f"--force-relabel to overwrite)")
            continue
        to_label.append(obj)

    for i, obj in enumerate(to_label):
        result = _vlm_label_segment(client, scene_image, obj)
        obj["label"] = result["label"]
        obj["label_confidence"] = result["confidence"]
        obj["is_object"] = result["is_object"]
        flag = "" if result["is_object"] else "  [noise]"
        print(f"  [{i + 1}/{len(to_label)}] {obj['id']}: "
              f"'{result['label']}' (conf={result['confidence']:.2f}"
              f"){flag}")

    # ── Containment + superset (with VLM verification) ──
    # Step 1: geometrically find all candidate parent/child pairs.
    # Step 2: ask the VLM to verify each pair (rejects bbox-overlap
    #         false positives where two distinct objects happen to
    #         share bbox space).
    # Step 3: use the verified pair set for both containment relabeling
    #         and superset warnings.
    #
    # This addresses a failure mode where Pass 1 mislabels a large
    # segment (e.g. calling a wide region "blue lit gaming mouse")
    # and containment then propagates that wrong label to legitimate
    # smaller objects inside its bbox (tissue boxes, speakers, etc.).
    # The verification step removes those false-positive pairs.
    candidate_pairs = _find_candidate_containment_pairs(
        objects_with_masks, threshold=CONTAINMENT_THRESHOLD,
    )
    if candidate_pairs:
        verified_pairs = _verify_containment_pairs(
            client, scene_image, objects_with_masks, candidate_pairs,
        )
    else:
        verified_pairs = set()
        print(f"\n── No geometric containment pairs above threshold "
              f"{CONTAINMENT_THRESHOLD}; skipping verification.")

    # Containment relabeling restricted to VLM-verified pairs.
    # Sub-parts of named objects get their parent's label so trajectory
    # references resolve to all segments of the same physical object.
    n_contained = _apply_containment_relabeling(
        objects_with_masks, threshold=CONTAINMENT_THRESHOLD,
        verified_pairs=verified_pairs,
    )
    if n_contained == 0:
        print(f"\n── Containment relabeling: no verified parent/child "
              f"relationships; nothing relabeled.")

    # Superset detection (warn only), also restricted to verified pairs.
    # If the VLM rejected a candidate parent/child pair, it doesn't
    # count as containment, so the "parent" doesn't become a superset.
    _detect_supersets(
        objects_with_masks, threshold=CONTAINMENT_THRESHOLD,
        verified_pairs=verified_pairs,
    )

    # ── IoU clustering + Pass 2 disambiguation ──
    # Group objects by their generic label (drop empty labels), then
    # for each group, cluster by IoU. Clusters of 1 are unique
    # instances and keep their label. Clusters of >1 segments sharing
    # high IoU are the same physical object — also keep their label
    # (the on_top_of resolver expands them naturally).
    # Multiple separate clusters under the same label means multiple
    # distinct instances; that's when pass 2 fires.
    print(f"\n── IoU clustering (threshold {IOU_MERGE_THRESHOLD})")
    by_label = defaultdict(list)
    for obj in objects_with_masks:
        lab = obj.get("label", "").strip()
        if not lab:
            continue
        if not obj.get("is_object", True):
            continue
        by_label[lab].append(obj)

    for label, group in by_label.items():
        if len(group) == 1:
            continue
        clusters = _cluster_by_iou(group, IOU_MERGE_THRESHOLD)
        if len(clusters) == 1:
            print(f"  '{label}': {len(group)} segments → 1 physical object "
                  f"(over-segmentation, keeping shared label)")
            continue

        # Multiple distinct instances — call VLM to disambiguate
        print(f"  '{label}': {len(group)} segments → {len(clusters)} "
              f"distinct instances; disambiguating...")
        # Use the first segment of each cluster as the "representative"
        # for the VLM call; relabel all segments in that cluster the same
        representatives = [cluster[0] for cluster in clusters]
        new_labels = _vlm_disambiguate_instances(
            client, scene_image, representatives, label
        )
        for cluster, new_label in zip(clusters, new_labels):
            for obj in cluster:
                obj["label"] = new_label
            print(f"     → cluster of {len(cluster)} → '{new_label}'")

    # ── Strip the in-memory mask field before writing (it's not JSON
    # serialisable and the JSON references mask files by path anyway) ──
    for obj in scene_data["objects"]:
        obj.pop("mask", None)

    # ── Apply dedup deletions ──
    # Redundant objects were already excluded from labeling. Now remove
    # them from the JSON entirely. The mask PNG files on disk are
    # preserved (we don't delete them) so the data is still available
    # for debugging, but the labeled scene_processed.json is a clean
    # representation of the final, deduped segmentation.
    if dedupe_masks and redundant_records:
        redundant_ids = {r["id"] for r in redundant_records}
        before = len(scene_data["objects"])
        scene_data["objects"] = [
            o for o in scene_data["objects"]
            if o["id"] not in redundant_ids
        ]
        print(f"\n── Dropped {before - len(scene_data['objects'])} "
              f"redundant object(s) from JSON")
        # Also remove the redundant_masks field if it was written by a
        # previous run — current behavior is to delete rather than
        # record.
        scene_data.pop("redundant_masks", None)

    # ── Write back ──
    with open(json_path, "w") as f:
        json.dump(scene_data, f, indent=2)
    print(f"\n✓ Wrote labels into {json_path}")


# ──────────────────────────────────────────────
# DEBUG OVERLAY
# ──────────────────────────────────────────────

def save_debug_overlay(scene_dir: str,
                       output_filename: str = "debug_segments_labeled.png") -> str:
    """
    Render a labeled visualization of the segmented scene. For each
    object, draws a translucent colored overlay of its mask and writes
    the object's id, label, and depth near its centroid. Useful for
    verifying labels against the actual segments.

    Reads scene_processed.json (and the mask files it references) from
    `scene_dir`. Writes the overlay PNG into the same directory.

    Returns the output file path.

    Unlike the preprocessor's debug image (which only had IDs and
    depths), this version includes the labels — so you can see at a
    glance which physical objects each segment corresponds to.
    """
    scene_dir = os.path.abspath(scene_dir)
    json_path = os.path.join(scene_dir, "scene_processed.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"No scene_processed.json in {scene_dir}")
    with open(json_path) as f:
        scene_data = json.load(f)

    image_path = scene_data["scene"]["image_path"]
    bg_image = cv2.imread(image_path)
    if bg_image is None:
        raise FileNotFoundError(f"Could not read scene image: {image_path}")

    overlay = bg_image.copy()
    # Distinct BGR colors cycled across objects so adjacent segments
    # don't share the same hue
    colours = [
        (255,  80,  80), ( 80, 255,  80), ( 80,  80, 255),
        (255, 255,  80), (255,  80, 255), ( 80, 255, 255),
        (200, 140,  80), (140,  80, 200), ( 80, 200, 140),
        (255, 160,  80), (160,  80, 255), ( 80, 255, 160),
    ]

    # Sort objects by area descending so smaller segments draw on top
    # and don't get hidden under bigger overlapping ones
    def _area(obj):
        return ((obj.get("x_max", 0) - obj.get("x_min", 0))
                * (obj.get("y_max", 0) - obj.get("y_min", 0)))
    sorted_objs = sorted(scene_data["objects"], key=_area, reverse=True)

    for i, obj in enumerate(sorted_objs):
        mp = obj.get("mask_path")
        if not mp or not os.path.exists(mp):
            continue
        mask = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue

        colour = colours[i % len(colours)]
        coloured = np.zeros_like(bg_image)
        coloured[mask > 0] = colour
        # Dimmer overlay so the text on top stays readable
        overlay = cv2.addWeighted(overlay, 1.0, coloured, 0.35, 0)

        # Compose the text: id, label (or "?" if empty), depth, noise flag
        label = obj.get("label", "").strip() or "?"
        depth = obj.get("base_depth_m", 0.0)
        is_obj = obj.get("is_object", True)
        flag = "" if is_obj else "  [noise]"
        text_line1 = f"{obj['id']}  {depth:.2f}m{flag}"
        text_line2 = f"{label}"

        # Position text near the centroid of the mask
        ys, xs = np.where(mask > 0)
        if not len(ys):
            continue
        cy = int(np.median(ys))
        cx = int(np.median(xs))

        # Draw two lines: id+depth above, label below.
        # Black outline plus white fill for legibility on any background.
        for line_idx, text in enumerate((text_line1, text_line2)):
            y = cy + line_idx * 22
            cv2.putText(overlay, text, (cx, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(overlay, text, (cx, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 1, cv2.LINE_AA)

    output_path = os.path.join(scene_dir, output_filename)
    cv2.imwrite(output_path, overlay)
    print(f"✓ Wrote labeled debug overlay → {output_path}")
    return output_path


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scene-dir", required=True,
        help="Directory containing scene_processed.json "
             "(e.g. output/processed_scene/desk)",
    )
    parser.add_argument(
        "--force-relabel", action="store_true",
        help="Re-label every object even if it already has a label. "
             "Default: skip objects with an existing label.",
    )
    parser.add_argument(
        "--save-debug-overlay", action="store_true",
        help="After labeling, render a labeled debug overlay "
             "(debug_segments_labeled.png) into the scene directory.",
    )
    parser.add_argument(
        "--debug-overlay-only", action="store_true",
        help="Skip labeling entirely. Just regenerate the labeled "
             "debug overlay from the current scene_processed.json. "
             "Useful after manual edits to the JSON.",
    )
    parser.add_argument(
        "--no-dedupe-masks", action="store_true",
        help="Skip the VLM mask deduplication step that picks one "
             "best mask per physical object before labeling. Default "
             "is to run dedup, which trims overlapping SAM2 "
             "over-segmentations to one mask per object.",
    )
    parser.add_argument(
        "--debug-dedup-views", action="store_true",
        help="Dump each dedup cluster's rendered VLM-input image plus a "
             "sidecar JSON of the raw VLM response into "
             "<scene_dir>/debug_dedup/. The PNG shows what the VLM saw; "
             "the JSON captures the prompt, raw response, any error, "
             "and the parsed grouping. Useful for diagnosing why a "
             "cluster was or wasn't merged.",
    )
    args = parser.parse_args()

    if args.debug_overlay_only:
        save_debug_overlay(args.scene_dir)
    else:
        label_scene(args.scene_dir,
                    force_relabel=args.force_relabel,
                    dedupe_masks=not args.no_dedupe_masks,
                    debug_dedup_views=args.debug_dedup_views)
        if args.save_debug_overlay:
            save_debug_overlay(args.scene_dir)