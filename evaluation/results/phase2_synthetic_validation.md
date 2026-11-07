| file | res | fps | vfr | codec | duration | frames_expected | frames_decoded | ts_mismatch | monotonic | truncation | irregular | max_gap_ms | sampled_fps | seek_exact | realtime_x | peak_mb | pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| syn1080p60.mp4 | 1920x1080 | 60.0 | False | h264 | 60.0 | 3600 | 3600 | 0 | True | False | 0 | 16.7 | 12.0 | 5/5 | 8.38 | 195 | True |
| vfr.mp4 | 320x240 | 30.0 | True | h264 | 3.0 | 75 | 75 | 0 | True | False | 1 | 533.3 | 9.89 | 5/5 | 185.61 | 218 | True |
| cfr60.mkv | 320x240 | 60.0 | False | h264 | 2.0 | 120 | 120 | 0 | True | False | 0 | 17.0 | 12.0 | 5/5 | 106.01 | 218 | True |
| clip25.avi | 320x240 | 25.0 | False | mpeg4 | 2.0 | 50 | 50 | 0 | True | False | 0 | 40.0 | 11.98 | 5/5 | 158.69 | 218 | True |
| offset.mkv | 320x240 | 30.0 | False | h264 | 2.0 | 60 | 60 | 0 | True | False | 0 | 34.0 | 11.9 | 5/5 | 145.0 | 218 | True |
| hdr.mp4 | 320x240 | 30.0 | False | h264 | 1.0 | 30 | 30 | 0 | True | False | 0 | 33.3 | 11.79 | 5/5 | 91.16 | 218 | True |
| trunc_faststart.mp4 | 320x240 | 30.0 | True | h264 | 1.1667 | 32 | 29 | 0 | True | True | 1 | 133.3 | 11.79 | 4/5 | 115.68 | 218 | False |
| trunc.mkv | 320x240 | 60.0 | False | h264 | 0.834 | 50 | 50 | 0 | True | True | 0 | 17.0 | 12.0 | 5/5 | 86.88 | 218 | False |
| trunc.avi | 320x240 | 25.0 | False | mpeg4 | 0.68 | 17 | 17 | 0 | True | True | 0 | 40.0 | 11.67 | 5/5 | 105.05 | 218 | False |
| screen.mov | rejected: 'screen.mov': format .mov is not supported. Accepted formats: .avi, .mkv, .mp4 |
| notes.mp4 | rejected: 'notes.mp4' is not a video file (content does not match any accepted container). Accepted formats: .avi, .mkv, .mp4 |

Warnings:
- **hdr.mp4**: HDR video (smpte2084): converted to 8-bit without tone mapping; colours will look washed out and brightness-based thresholds may be unreliable
- **trunc_faststart.mp4**: container declares 120 frames / 4.0 s but only 32 frames / 1.1667 s are present: file is probably truncated
- **trunc_faststart.mp4**: decoding stopped after 29 of 32 frames (at 0.93s): file may be truncated or damaged
- **trunc.mkv**: container declares ? frames / 2.0 s but only 50 frames / 0.834 s are present: file is probably truncated
- **trunc.avi**: container declares 50 frames / 1.0 s but only 17 frames / 0.68 s are present: file is probably truncated
