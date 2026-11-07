"""Compute-device selection for the deep-learning detectors (YOLOv8).

The SRS assumes a CUDA GPU; the development machine is Apple Silicon. Detectors ask
for a device through this one function so the same code runs on CUDA, Apple MPS or
CPU. PyTorch is imported lazily: it is only installed from Phase 6 onward.
"""

from __future__ import annotations

from typing import Literal

Device = Literal["cuda", "mps", "cpu"]


def available_devices() -> list[Device]:
    devices: list[Device] = []
    try:
        import torch
    except ImportError:
        return ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        devices.append("mps")
    devices.append("cpu")
    return devices


def select_device(preference: str = "auto") -> Device:
    """Return ``preference`` if available, else the best available device."""
    devices = available_devices()
    if preference != "auto":
        if preference not in devices:
            raise RuntimeError(
                f"requested device '{preference}' is not available (available: {devices})"
            )
        return preference  # type: ignore[return-value]
    return devices[0]
