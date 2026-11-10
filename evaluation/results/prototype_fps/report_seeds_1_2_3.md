# Prototype FPS service evaluation — seeds [1, 2, 3]

- **mandel_s1**: GT 5, TP 5, FP 0, FN 0
- **photo_s1**: GT 4, TP 4, FP 0, FN 0
- **mandel_s2**: GT 4, TP 4, FP 0, FN 0
- **photo_s2**: GT 4, TP 3, FP 0, FN 1
  - FN freeze 16.65-17.19s (every=)
- **mandel_s3**: GT 5, TP 5, FP 0, FN 0
- **photo_s3**: GT 5, TP 5, FP 0, FN 0

| Event | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| stutter | 11 | 0 | 0 | 1.000 | 1.000 |
| freeze | 8 | 0 | 1 | 1.000 | 0.889 |
| fps_drop | 7 | 0 | 0 | 1.000 | 1.000 |
