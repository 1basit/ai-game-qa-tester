# Phase 5 evaluation — animation glitches (HELD-OUT seeds [1, 2, 3])

## HELD-OUT seeds [1, 2, 3] — animation_glitch

- **p5_v1game_s1** [animation_glitch]: TP 5, FP 1, FN 0
  - FP jitter 13.12-13.15s (conf 0.80)
- **p5_mandel_s1** [animation_glitch]: TP 6, FP 0, FN 0
- **p5_photo_s1** [animation_glitch]: TP 6, FP 0, FN 0
- **p5_v1game_s2** [animation_glitch]: TP 6, FP 1, FN 0
  - FP jitter 16.55-16.58s (conf 0.80)
- **p5_mandel_s2** [animation_glitch]: TP 4, FP 0, FN 2
  - FN jitter 13.93-14.31s
  - FN unnatural_transition 15.74-15.84s
- **p5_photo_s2** [animation_glitch]: TP 6, FP 0, FN 0
- **p5_v1game_s3** [animation_glitch]: TP 5, FP 1, FN 1
  - FP jitter 15.22-15.25s (conf 0.80)
  - FN jitter 11.78-12.19s
- **p5_mandel_s3** [animation_glitch]: TP 4, FP 0, FN 2
  - FN unnatural_transition 12.44-12.54s
  - FN jitter 1.71-2.58s
- **p5_photo_s3** [animation_glitch]: TP 5, FP 0, FN 0

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p5_v1game_s1 | 7 | 6.3 | 132 | {"frames": 829} |
| p5_mandel_s1 | 6 | 9.5 | 127 | {"frames": 1200} |
| p5_photo_s1 | 6 | 8.4 | 128 | {"frames": 1078} |
| p5_v1game_s2 | 8 | 7.7 | 134 | {"frames": 1035} |
| p5_mandel_s2 | 4 | 8.8 | 129 | {"frames": 1143} |
| p5_photo_s2 | 6 | 9.1 | 123 | {"frames": 1122} |
| p5_v1game_s3 | 6 | 7.2 | 132 | {"frames": 955} |
| p5_mandel_s3 | 4 | 8.6 | 129 | {"frames": 1100} |
| p5_photo_s3 | 5 | 8.0 | 124 | {"frames": 994} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| animation_glitch | 9 | 47 | 3 | 5 | 0.940 | 0.904 | 0.922 | 1.142 |

