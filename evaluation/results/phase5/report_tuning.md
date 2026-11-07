# Phase 5 evaluation — animation glitches (TUNING set (seed 0))

## TUNING set (seed 0) — animation_glitch

- **p5_v1game_clean** [animation_glitch]: TP 0, FP 0, FN 0
- **p5_v1game_s0** [animation_glitch]: TP 5, FP 0, FN 1
  - FN unnatural_transition 7.60-7.70s
- **p5_mandel_clean** [animation_glitch]: TP 0, FP 0, FN 0
- **p5_mandel_s0** [animation_glitch]: TP 4, FP 0, FN 1
  - FN unnatural_transition 11.15-11.25s
- **p5_photo_clean** [animation_glitch]: TP 0, FP 0, FN 0
- **p5_photo_s0** [animation_glitch]: TP 5, FP 0, FN 1
  - FN unnatural_transition 10.73-10.83s

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p5_v1game_clean | 1 | 8.5 | 130 | {"frames": 1111} |
| p5_v1game_s0 | 6 | 7.0 | 130 | {"frames": 905} |
| p5_mandel_clean | 0 | 9.8 | 123 | {"frames": 1200} |
| p5_mandel_s0 | 4 | 7.8 | 124 | {"frames": 968} |
| p5_photo_clean | 0 | 9.6 | 125 | {"frames": 1200} |
| p5_photo_s0 | 5 | 7.6 | 124 | {"frames": 939} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| animation_glitch | 6 | 14 | 0 | 3 | 1.000 | 0.824 | 0.903 | 0.000 |

## Real footage (unlabelled) — animation_glitch


| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p | 27 | 117.0 | 102 | {"frames": 11955} |
