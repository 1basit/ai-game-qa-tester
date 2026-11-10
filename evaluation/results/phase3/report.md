# Phase 3 evaluation — FPS drop / frozen frame

## HELD-OUT synthetic, seeds [2, 3, 4, 5] (generated after tuning) — fps_drop

- **p3_v1game_heldout_s2** [fps_drop]: TP 5, FP 0, FN 0
- **p3_mandel_heldout_s2** [fps_drop]: TP 6, FP 0, FN 0
- **p3_v1game_heldout_s3** [fps_drop]: TP 6, FP 0, FN 0
- **p3_mandel_heldout_s3** [fps_drop]: TP 6, FP 0, FN 0
- **p3_v1game_heldout_s4** [fps_drop]: TP 5, FP 0, FN 1
  - FN frozen_frame 17.03-17.84s
- **p3_mandel_heldout_s4** [fps_drop]: TP 6, FP 0, FN 0
- **p3_v1game_heldout_s5** [fps_drop]: TP 5, FP 0, FN 0
- **p3_mandel_heldout_s5** [fps_drop]: TP 6, FP 0, FN 0

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p3_v1game_heldout_s2 | 5 | 1.3 | 847 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 51.0, "estimated_render_fps_p10": 21.6, "measurable_fraction": 0.901, "missed_frames": 251, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_heldout_s2 | 6 | 2.9 | 413 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 51.0, "estimated_render_fps_p10": 21.0, "measurable_fraction": 1.0, "missed_frames": 263, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_v1game_heldout_s3 | 6 | 1.1 | 1002 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 51.0, "estimated_render_fps_p10": 25.6, "measurable_fraction": 0.901, "missed_frames": 234, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_heldout_s3 | 6 | 1.8 | 657 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 55.5, "estimated_render_fps_p10": 22.0, "measurable_fraction": 1.0, "missed_frames": 247, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_v1game_heldout_s4 | 5 | 1.1 | 1024 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 47.5, "estimated_render_fps_p10": 18.0, "measurable_fraction": 0.845, "missed_frames": 266, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_heldout_s4 | 6 | 2.3 | 525 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 51.0, "estimated_render_fps_p10": 21.0, "measurable_fraction": 1.0, "missed_frames": 274, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_v1game_heldout_s5 | 5 | 1.1 | 973 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 48.0, "estimated_render_fps_p10": 23.0, "measurable_fraction": 0.901, "missed_frames": 253, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_heldout_s5 | 6 | 2.1 | 579 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 41.5, "estimated_render_fps_p10": 15.0, "measurable_fraction": 1.0, "missed_frames": 387, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| fps_drop | 8 | 45 | 0 | 1 | 1.000 | 0.978 | 0.989 | 0.000 |

## TUNING set — synthetic (injected) — fps_drop

- **p3_v1game_clean** [fps_drop]: TP 0, FP 0, FN 0
- **p3_v1game_cfr** [fps_drop]: TP 6, FP 0, FN 0
- **p3_v1game_vfr** [fps_drop]: TP 4, FP 0, FN 0
- **p3_mandel_clean** [fps_drop]: TP 0, FP 0, FN 0
- **p3_mandel_cfr** [fps_drop]: TP 6, FP 0, FN 0
- **p3_mandel_vfr** [fps_drop]: TP 4, FP 0, FN 0

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p3_v1game_clean | 0 | 1.1 | 984 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 57.0, "estimated_render_fps_p10": 55.0, "measurable_fraction": 0.93, "missed_frames": 46, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_v1game_cfr | 6 | 1.1 | 991 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 44.5, "estimated_render_fps_p10": 21.0, "measurable_fraction": 0.93, "missed_frames": 302, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_v1game_vfr | 4 | 1.0 | 968 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 53.5, "estimated_render_fps_p10": 29.0, "measurable_fraction": 0.93, "missed_frames": 36, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_clean | 0 | 2.7 | 449 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 60.0, "estimated_render_fps_p10": 60.0, "measurable_fraction": 1.0, "missed_frames": 0, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_cfr | 6 | 2.4 | 499 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 49.0, "estimated_render_fps_p10": 21.0, "measurable_fraction": 1.0, "missed_frames": 281, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_vfr | 4 | 2.4 | 437 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 60.0, "estimated_render_fps_p10": 30.0, "measurable_fraction": 1.0, "missed_frames": 0, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| fps_drop | 6 | 20 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0.000 |

## Real footage (unlabelled) — fps_drop


| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p | 1 | 24.7 | 484 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 57.0, "estimated_render_fps_p10": 49.4, "measurable_fraction": 0.092, "missed_frames": 130, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
