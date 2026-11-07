# Phase 4 evaluation — texture pop-in (TUNING set (seed 0))

## TUNING set (seed 0) — texture_pop_in

- **p4_v1game_clean** [texture_pop_in]: TP 0, FP 0, FN 0
- **p4_v1game_s0** [texture_pop_in]: TP 5, FP 1, FN 2
  - FP unrendered_texture 5.17-5.18s (conf 1.00)
  - FN texture_pop_in 8.69-8.84s
  - FN texture_pop_in 9.47-9.62s
- **p4_mandel_clean** [texture_pop_in]: TP 0, FP 1, FN 0
  - FP texture_pop_in 1.23-1.25s (conf 0.86)
- **p4_mandel_s0** [texture_pop_in]: TP 2, FP 0, FN 9
  - FN texture_pop_in 15.97-16.12s
  - FN texture_pop_in 16.78-16.93s
  - FN texture_pop_in 5.95-6.10s
  - FN texture_pop_in 6.88-7.03s
  - FN texture_pop_in 11.62-11.77s
  - FN texture_pop_in 13.09-13.24s
  - FN texture_pop_in 18.27-18.42s
  - FN texture_pop_in 19.14-19.29s
  - FN texture_pop_in 2.02-2.17s
- **p4_photo_clean** [texture_pop_in]: TP 0, FP 0, FN 0
- **p4_photo_s0** [texture_pop_in]: TP 8, FP 0, FN 1
  - FN texture_pop_in 6.74-6.89s

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p4_v1game_clean | 0 | 14.3 | 77 | {"frames_analysed": 1111, "frames_skipped_unaligned_or_cut": 4, "skipped_fraction": 0.004} |
| p4_v1game_s0 | 6 | 14.2 | 78 | {"frames_analysed": 1111, "frames_skipped_unaligned_or_cut": 5, "skipped_fraction": 0.005} |
| p4_mandel_clean | 1 | 15.6 | 77 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 88, "skipped_fraction": 0.073} |
| p4_mandel_s0 | 2 | 15.6 | 77 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 62, "skipped_fraction": 0.052} |
| p4_photo_clean | 0 | 13.6 | 88 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 0, "skipped_fraction": 0.0} |
| p4_photo_s0 | 8 | 13.5 | 89 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 0, "skipped_fraction": 0.0} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| texture_pop_in | 6 | 15 | 2 | 12 | 0.882 | 0.556 | 0.682 | 1.025 |

## Real footage (unlabelled) — texture_pop_in


| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| YTDown.com_YouTube_Media_J8HB1-IQFxc_How-to-fix-Weapons-Hands-Clipping-Into-Walls-in-Unity-URP-SRP_001_1080p | 9 | 111.3 | 107 | {"frames_analysed": 11955, "frames_skipped_unaligned_or_cut": 18, "skipped_fraction": 0.002} |
