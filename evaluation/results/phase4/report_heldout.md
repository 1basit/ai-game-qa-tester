# Phase 4 evaluation — texture pop-in (HELD-OUT seeds [1, 2, 3])

## HELD-OUT seeds [1, 2, 3] — texture_pop_in

- **p4_v1game_s1** [texture_pop_in]: TP 6, FP 2, FN 0
  - FP texture_pop_in 11.27-11.28s (conf 0.57)
  - FP texture_pop_in 14.08-14.10s (conf 0.62)
- **p4_mandel_s1** [texture_pop_in]: TP 3, FP 1, FN 6
  - FP texture_pop_in 1.23-1.25s (conf 0.90)
  - FN texture_pop_in 4.35-4.50s
  - FN texture_pop_in 5.82-5.97s
  - FN texture_pop_in 2.07-2.22s
  - FN texture_pop_in 3.03-3.18s
  - FN texture_pop_in 11.67-11.82s
  - FN texture_pop_in 12.61-12.76s
- **p4_photo_s1** [texture_pop_in]: TP 6, FP 0, FN 3
  - FN texture_pop_in 2.33-2.48s
  - FN texture_pop_in 10.34-10.49s
  - FN texture_pop_in 5.02-5.17s
- **p4_v1game_s2** [texture_pop_in]: TP 4, FP 2, FN 0
  - FP texture_pop_in 14.08-14.10s (conf 0.64)
  - FP unrendered_texture 15.77-15.78s (conf 1.00)
- **p4_mandel_s2** [texture_pop_in]: TP 5, FP 1, FN 2
  - FP texture_pop_in 1.23-1.25s (conf 0.90)
  - FN texture_pop_in 3.59-3.74s
  - FN texture_pop_in 4.19-4.34s
- **p4_photo_s2** [texture_pop_in]: TP 7, FP 0, FN 1
  - FN texture_pop_in 10.00-10.15s
- **p4_v1game_s3** [texture_pop_in]: TP 6, FP 2, FN 0
  - FP texture_pop_in 11.27-11.28s (conf 0.58)
  - FP texture_pop_in 14.08-14.10s (conf 0.64)
- **p4_mandel_s3** [texture_pop_in]: TP 3, FP 1, FN 5
  - FP texture_pop_in 1.23-1.25s (conf 0.90)
  - FN unrendered_texture 14.82-15.91s
  - FN texture_pop_in 3.38-3.53s
  - FN texture_pop_in 4.77-4.92s
  - FN texture_pop_in 6.34-6.49s
  - FN texture_pop_in 6.97-7.12s
- **p4_photo_s3** [texture_pop_in]: TP 5, FP 0, FN 2
  - FN texture_pop_in 9.62-9.77s
  - FN texture_pop_in 1.61-1.76s

| video | detections | wall s | frames/s | detector summary |
|---|---|---|---|---|
| p4_v1game_s1 | 8 | 14.3 | 78 | {"frames_analysed": 1111, "frames_skipped_unaligned_or_cut": 5, "skipped_fraction": 0.005} |
| p4_mandel_s1 | 4 | 15.6 | 77 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 53, "skipped_fraction": 0.044} |
| p4_photo_s1 | 6 | 13.5 | 89 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 0, "skipped_fraction": 0.0} |
| p4_v1game_s2 | 6 | 14.3 | 78 | {"frames_analysed": 1111, "frames_skipped_unaligned_or_cut": 3, "skipped_fraction": 0.003} |
| p4_mandel_s2 | 6 | 15.6 | 77 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 70, "skipped_fraction": 0.058} |
| p4_photo_s2 | 7 | 13.7 | 88 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 0, "skipped_fraction": 0.0} |
| p4_v1game_s3 | 8 | 14.3 | 78 | {"frames_analysed": 1111, "frames_skipped_unaligned_or_cut": 2, "skipped_fraction": 0.002} |
| p4_mandel_s3 | 4 | 15.5 | 77 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 72, "skipped_fraction": 0.06} |
| p4_photo_s3 | 5 | 13.5 | 89 | {"frames_analysed": 1200, "frames_skipped_unaligned_or_cut": 0, "skipped_fraction": 0.0} |

### Aggregate (subtype must match)

| Category | Videos | TP | FP | FN | Precision | Recall | F1 | FP/min |
|---|---|---|---|---|---|---|---|---|
| texture_pop_in | 9 | 45 | 9 | 19 | 0.833 | 0.703 | 0.763 | 3.076 |

