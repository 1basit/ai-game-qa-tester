# Phase 3 evaluation — FPS drop / frozen frame

## HELD-OUT synthetic, seed 1 (generated after tuning) — fps_drop

- **p3_v1game_heldout_s1** [fps_drop]: TP 4, FP 0, FN 0
- **p3_mandel_heldout_s1** [fps_drop]: TP 5, FP 0, FN 0

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p3_v1game_heldout_s1 | 4 | 1.1 | 1048 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 54.5, "estimated_render_fps_p10": 25.6, "measurable_fraction": 0.901, "missed_frames": 219, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_heldout_s1 | 5 | 1.8 | 667 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 48.5, "estimated_render_fps_p10": 18.0, "measurable_fraction": 1.0, "missed_frames": 307, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| fps_drop | 2 | 9 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0.000 |

## TUNING set — synthetic (injected) — fps_drop

- **p3_v1game_clean** [fps_drop]: TP 0, FP 0, FN 0
- **p3_v1game_cfr** [fps_drop]: TP 6, FP 0, FN 0
- **p3_v1game_vfr** [fps_drop]: TP 4, FP 0, FN 0
- **p3_mandel_clean** [fps_drop]: TP 0, FP 0, FN 0
- **p3_mandel_cfr** [fps_drop]: TP 6, FP 0, FN 0
- **p3_mandel_vfr** [fps_drop]: TP 4, FP 0, FN 0

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p3_v1game_clean | 0 | 1.1 | 1023 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 57.0, "estimated_render_fps_p10": 55.0, "measurable_fraction": 0.93, "missed_frames": 46, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_v1game_cfr | 6 | 1.1 | 1038 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 44.5, "estimated_render_fps_p10": 21.0, "measurable_fraction": 0.93, "missed_frames": 302, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_v1game_vfr | 4 | 0.9 | 1014 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 54.0, "estimated_render_fps_p10": 28.8, "measurable_fraction": 0.915, "missed_frames": 36, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_clean | 0 | 2.5 | 484 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 60.0, "estimated_render_fps_p10": 60.0, "measurable_fraction": 1.0, "missed_frames": 0, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_cfr | 6 | 2.3 | 531 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 49.0, "estimated_render_fps_p10": 21.0, "measurable_fraction": 1.0, "missed_frames": 281, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
| p3_mandel_vfr | 4 | 2.1 | 488 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 60.0, "estimated_render_fps_p10": 30.0, "measurable_fraction": 1.0, "missed_frames": 0, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| fps_drop | 6 | 20 | 0 | 0 | 1.000 | 1.000 | 1.000 | 0.000 |

## Real footage (unlabelled) — fps_drop


| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p | 1 | 23.2 | 515 | {"recording_fps": 60.0, "target_fps": 60.0, "estimated_render_fps_median": 57.0, "estimated_render_fps_p10": 49.4, "measurable_fraction": 0.092, "missed_frames": 130, "note": "FPS can only be measured while the scene is moving; static stretches are excluded"} |
