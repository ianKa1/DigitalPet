"""
Compositor package: insert a DigitalPet's animation library into a real scene
with depth-aware occlusion and perspective scale.

Pipeline (offline):
  scene.png + scene.json
       │
       ▼
  scene_preprocessor.preprocess()      → scene_data/scene_processed.json
                                         + bg_depth_meters.npy + masks/
  pet animations/*.gif
       │
       ▼
  character_extractor.extract_pet()    → animations/extracted/<action>/
                                           frames/  +  masks/
                                         + animations/extracted/canvas.json

Runtime:
  scene_processed.json + trajectory.json + character.json
       │
       ▼
  compositor.composite()               → output_composite.mp4
"""

from .compositor import composite
from .scene_preprocessor import preprocess as preprocess_scene
from .character_extractor import extract_pet
from .animation_library import AnimationLibrary
from .scene import SceneContext

__all__ = [
    "composite",
    "preprocess_scene",
    "extract_pet",
    "AnimationLibrary",
    "SceneContext",
]
