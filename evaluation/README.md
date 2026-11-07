# Evaluation data

Every detector is validated against manually labelled footage before integration
(see `docs/ROADMAP.md` §5).

```
evaluation/
├── videos/          footage (git-ignored; keep a list of sources in sources.md)
├── ground_truth/    one label file per video: <video_id>.json
├── results/         evaluation output per detector run (tracked)
└── label_template.json
```

## Labelling rules

1. Copy `label_template.json` to `ground_truth/<video_id>.json`.
2. List in `reviewed_categories` **every category you watched the whole video for**.
   A reviewed category with no events means "clean for this category" — predictions
   there count as false positives. Do not list categories you did not check.
3. One event per defect occurrence: `start_s` = first frame the defect is visible,
   `end_s` = last frame. For a one-frame defect, `start_s == end_s`.
4. `subtype` is optional but recommended (allowed values: see `SUBTYPES` in
   `backend/src/gameqa/core/schemas.py`).
5. `bbox` (normalised 0–1) is only needed for NPC and clipping events used for mAP.
6. Set `synthetic: true` for footage with artificially injected defects. Synthetic
   results are always reported separately from real-footage results.
7. Record where the footage came from in `source` (self-recorded / URL / synthetic).

## Running an evaluation

```bash
backend/.venv/bin/gameqa evaluate -p predictions/*.json -g evaluation/ground_truth -o evaluation/results/<run-name>
```
