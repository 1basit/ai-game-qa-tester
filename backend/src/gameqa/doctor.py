"""Environment check (`gameqa doctor`).

Verifies — by actually running things, not just importing — that this machine can
run the parts of the system built so far, and reports what later phases still need.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Status = Literal["ok", "warn", "fail", "info"]


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str


def _version(module: str) -> str | None:
    try:
        mod = importlib.import_module(module)
    except Exception:
        return None
    return str(getattr(mod, "__version__", "installed"))


def check_python() -> CheckResult:
    v = sys.version_info
    ok = v >= (3, 10)
    return CheckResult(
        "python", "ok" if ok else "fail", f"{platform.python_version()} ({sys.executable})"
    )


def check_core_packages() -> list[CheckResult]:
    out = []
    for label, module in [
        ("numpy", "numpy"),
        ("opencv", "cv2"),
        ("pydantic", "pydantic"),
        ("pydantic-settings", "pydantic_settings"),
        ("pyyaml", "yaml"),
    ]:
        ver = _version(module)
        if ver is None:
            out.append(CheckResult(label, "fail", "not installed"))
        elif module == "cv2" and not ver.startswith("4."):
            out.append(CheckResult(label, "warn", f"{ver} (SRS specifies OpenCV 4.x)"))
        else:
            out.append(CheckResult(label, "ok", ver))
    return out


def check_phase_packages() -> list[CheckResult]:
    """Packages that later phases install. Missing = expected at this stage."""
    out = []
    for label, module, phase in [
        ("scikit-image", "skimage", "Phase 4 (SSIM)"),
        ("torch", "torch", "Phase 6 (YOLOv8 backend)"),
        ("ultralytics", "ultralytics", "Phase 6 (YOLOv8)"),
        ("mediapipe", "mediapipe", "Phase 6 (pose)"),
        ("fastapi", "fastapi", "Phase 10 (API)"),
        ("sqlalchemy", "sqlalchemy", "Phase 10 (database)"),
        ("reportlab", "reportlab", "Phase 13 (PDF)"),
    ]:
        ver = _version(module)
        out.append(
            CheckResult(label, "ok" if ver else "info", ver if ver else f"not yet installed — {phase}")
        )
    return out


def _run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def check_ffmpeg() -> list[CheckResult]:
    out = []
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if not path:
            out.append(CheckResult(tool, "fail", "not found on PATH (needed for probing and clips)"))
            continue
        first = _run([tool, "-version"]).stdout.splitlines()[:1]
        out.append(CheckResult(tool, "ok", (first[0] if first else path)))
    if shutil.which("ffmpeg"):
        enc = _run(["ffmpeg", "-hide_banner", "-encoders"]).stdout
        has = "libx264" in enc
        out.append(
            CheckResult(
                "ffmpeg libx264",
                "ok" if has else "warn",
                "H.264 encoder available (browser-playable clips)"
                if has
                else "libx264 missing — evidence clips would not play in browsers",
            )
        )
    return out


def check_opencv_decode() -> CheckResult:
    """Encode a known synthetic clip with ffmpeg and decode it with OpenCV."""
    if not shutil.which("ffmpeg"):
        return CheckResult("opencv decode", "fail", "skipped: ffmpeg missing")
    try:
        import cv2
    except ImportError:
        return CheckResult("opencv decode", "fail", "opencv not installed")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "probe.mp4"
        proc = _run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc=size=320x240:rate=25:duration=2",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path),
            ]
        )
        if proc.returncode != 0:
            return CheckResult("opencv decode", "fail", f"ffmpeg could not encode test clip: {proc.stderr.strip()[:200]}")
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return CheckResult("opencv decode", "fail", "cv2.VideoCapture could not open an H.264 mp4")
        n, last_ts, monotonic, shape = 0, -1.0, True, None
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts = cap.get(cv2.CAP_PROP_POS_MSEC)
            monotonic &= ts > last_ts
            last_ts, shape = ts, frame.shape
            n += 1
        cap.release()
    if n != 50 or shape != (240, 320, 3) or not monotonic:
        return CheckResult(
            "opencv decode", "fail",
            f"expected 50 frames of 240x320x3 with increasing timestamps; got {n} frames, shape {shape}, monotonic={monotonic}",
        )
    return CheckResult("opencv decode", "ok", "H.264 mp4 decoded: 50/50 frames, timestamps increasing")


def check_config_and_storage() -> list[CheckResult]:
    from gameqa.config import load_settings

    try:
        s = load_settings()
    except Exception as exc:  # noqa: BLE001 - report any config problem
        return [CheckResult("config", "fail", str(exc))]
    out = [CheckResult("config", "ok", f"loaded {s.config_file}")]
    if not (10 <= s.video.analysis_fps <= 15):
        out.append(CheckResult("analysis_fps", "warn", f"{s.video.analysis_fps} is outside FR-2's 10-15 FPS"))
    try:
        s.paths.ensure()
        probe = s.paths.data_dir / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        out.append(CheckResult("storage", "ok", f"data dir writable: {s.paths.data_dir}"))
    except OSError as exc:
        out.append(CheckResult("storage", "fail", f"cannot write data dir: {exc}"))
        return out
    free_gb = shutil.disk_usage(s.paths.data_dir).free / 1024**3
    out.append(
        CheckResult(
            "disk space",
            "ok" if free_gb >= 30 else "warn",
            f"{free_gb:.0f} GB free (SRS: ~20 GB dataset + uploads and evidence)",
        )
    )
    return out


def check_hardware() -> list[CheckResult]:
    from gameqa.core.device import available_devices

    out = []
    try:
        ram_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
        out.append(
            CheckResult(
                "memory", "ok" if ram_gb >= 15.5 else "warn",
                f"{ram_gb:.0f} GB RAM (SRS recommends 16 GB)",
            )
        )
    except (ValueError, OSError, AttributeError):
        out.append(CheckResult("memory", "info", "could not determine RAM"))
    out.append(CheckResult("cpu", "info", f"{platform.machine()} — {platform.processor() or platform.platform()}"))
    devices = available_devices()
    if _version("torch") is None:
        out.append(CheckResult("compute device", "info", "torch not installed yet; device chosen in Phase 6"))
    elif "cuda" in devices:
        out.append(CheckResult("compute device", "ok", f"CUDA available ({devices})"))
    else:
        out.append(
            CheckResult(
                "compute device", "warn",
                f"no CUDA (SRS target hardware); using {devices[0]} — throughput will differ",
            )
        )
    return out


def run_all() -> list[CheckResult]:
    results = [check_python()]
    results += check_core_packages()
    results += check_ffmpeg()
    results.append(check_opencv_decode())
    results += check_config_and_storage()
    results += check_hardware()
    results += check_phase_packages()
    return results


def as_dicts(results: list[CheckResult]) -> list[dict[str, str]]:
    return [asdict(r) for r in results]
