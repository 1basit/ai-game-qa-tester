# Phase 6 — CLI and GUI on the test set

All videos are derived from the ONE real recording (see backend/scripts/phase6_test.py).

| Video | Variant | CLI exit / s | GUI | Same result | Measurable | Eff. FPS median / min | Freeze / drop / stutter | Ground truth / error |
|---|---|---|---|---|---|---|---|---|
| real_full_1080p60.mp4 | real recording (original) | 0 / 26.1 | done | yes | 9 % | 57.0 / 5.0 | 1 / 0 / 4 |  |
| real_gameplay_20s.mp4 | real, first 20 s (gameplay), stream copy | 0 / 4.0 | done | yes | 94 % | 57.0 / 5.0 | 1 / 0 / 4 |  |
| real_gameplay_20s.mkv | real, MKV container (stream copy) | 0 / 4.0 | done | yes | 94 % | 57.0 / 5.0 | 1 / 0 / 4 |  |
| real_gameplay_720p.avi | real, AVI container, MPEG-4 Part 2, 720p | 0 / 2.5 | done | yes | 83 % | 58.0 / 51.0 | 0 / 0 / 5 |  |
| real_gameplay_30fps.mp4 | real, resampled to 30 FPS (target 30) | 0 / 2.7 | done | yes | 95 % | 30.0 / 2.0 | 1 / 0 / 1 |  |
| real_gameplay_vfr.mp4 | real, repeated frames removed -> variable frame rate | 0 / 3.7 | done | yes | 87 % | 57.0 / 47.0 | 1 / 0 / 4 |  |
| real_editor_static_30s.mp4 | real, 30 s of the (mostly static) Unity editor | 0 / 5.1 | done | yes | 0 % | None / None | 0 / 0 / 0 |  |
| real_gameplay_truncated.mp4 | real 20 s file cut to half its bytes (damaged) | 2 / 0.6 | failed | — |  |  |  | cannot read video 'real_gameplay_truncated.mp4': the file is damaged or incomplete (Invalid data found when processing input) |
| tiny_2_frames.mp4 | real, only 2 frames | 2 / 0.7 | failed | — |  |  |  | video too short to analyse (fewer than 3 frames) |
| gameplay clip ü (copy).mp4 | real 20 s, file name with spaces / non-ASCII | 0 / 3.9 | done | yes | 94 % | 57.0 / 5.0 | 1 / 0 / 4 |  |
| inject_freeze.mp4 | real gameplay 0–18 s, 720p, freeze injected (10.0, 10.8) | 0 / 2.4 | done | yes | 93 % | 57.0 / 13.0 | 1 / 0 / 4 | FOUND freeze 10.00–10.80 s (injected 10.0–10.8 s) |
| inject_drop.mp4 | real gameplay 0–18 s, 720p, 20 FPS drop injected (4.0, 6.5) | 0 / 2.4 | done | yes | 93 % | 56.5 / 18.0 | 0 / 1 / 3 | FOUND fps_drop 3.50–6.75 s (injected 4.0–6.5 s) |
| does_not_exist.mp4 | missing path | 2 / 0.6 | not uploadable (not a file) | — |  |  |  | '/Users/amh/Desktop/FYP/evaluation/synthetic/phase6/invalid/does_not_exist.mp4' does not exist or is not a file |
| notes.txt | unsupported extension .txt | 2 / 0.5 | rejected 415 | — |  |  |  | 'notes.txt': format .txt is not supported. Accepted formats: .avi, .mkv, .mp4 |
| clip.mov | unsupported extension .mov | 2 / 0.6 | rejected 415 | — |  |  |  | 'clip.mov': format .mov is not supported. Accepted formats: .avi, .mkv, .mp4 |
| text_renamed.mp4 | text file renamed .mp4 | 2 / 0.6 | failed | — |  |  |  | 'text_renamed.mp4' is not a video file (content does not match any accepted container). Accepted formats: .avi, .mkv, .mp4 |
| empty.mp4 | 0-byte .mp4 | 2 / 0.5 | failed | — |  |  |  | 'empty.mp4' is empty |
| a_folder.mp4 | folder named .mp4 | 2 / 0.5 | not uploadable (not a file) | — |  |  |  | '/Users/amh/Desktop/FYP/evaluation/synthetic/phase6/invalid/a_folder.mp4' does not exist or is not a file |
