"""Defect detectors. Importing this package registers every detector by name."""

from gameqa.detectors.animation import AnimationGlitchDetector
from gameqa.detectors.clipping import ClippingDetector
from gameqa.detectors.fps import FpsDropDetector
from gameqa.detectors.npc import NpcAnomalyDetector
from gameqa.detectors.texture import TexturePopInDetector

__all__ = ["AnimationGlitchDetector", "ClippingDetector", "FpsDropDetector", "NpcAnomalyDetector", "TexturePopInDetector"]
