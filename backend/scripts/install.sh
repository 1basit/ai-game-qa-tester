#!/usr/bin/env bash
# Reproducible backend install (macOS / Linux). Run from the repository root:
#   backend/scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3.13}
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[ml,api,dev]"
# ultralytics depends on opencv-python and mediapipe on opencv-contrib-python; both install a
# 'cv2' package and overwrite each other (cv2 became 5.0). Keep exactly one OpenCV 4.x build:
.venv/bin/pip uninstall -y -q opencv-python opencv-contrib-python opencv-python-headless || true
.venv/bin/pip install -q --force-reinstall --no-deps "opencv-contrib-python-headless>=4.10,<5"
# model weights (official sources): YOLOv8n from Ultralytics, PoseLandmarker from Google
mkdir -p ../data/models
[ -f ../data/models/pose_landmarker_full.task ] || curl -sSfL -o ../data/models/pose_landmarker_full.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task
[ -f ../data/models/yolov8n.pt ] || (cd ../data/models && ../../backend/.venv/bin/python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')")
.venv/bin/gameqa doctor
echo "note: 'pip check' lists opencv-python / opencv-contrib-python as missing; that is expected (see above)."
