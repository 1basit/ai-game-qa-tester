"""Writes one analysis to its output folder: analysis.json, timeline.csv, windows.json,
charts/*.png and FPS_ANALYSIS_REPORT.docx."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from gameqa.fps_service.analysis import FpsAnalysisResult


def save_results(result: FpsAnalysisResult, tl: dict, folder: Path, report: bool = True) -> dict[str, Path]:
    from gameqa.fps_service.charts import make_charts

    folder.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    files["analysis_json"] = folder / "analysis.json"
    files["analysis_json"].write_text(result.model_dump_json(indent=2), encoding="utf-8")
    files["timeline_csv"] = folder / "timeline.csv"
    with open(files["timeline_csv"], "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame_index", "time_s", "interval_ms", "difference", "repeated", "missed_while_moving", "moving"])
        prev = None
        for i, t in enumerate(tl["time_s"]):
            w.writerow([tl["frame_index"][i], f"{t:.6f}", "" if prev is None else f"{(t - prev) * 1000:.3f}",
                        "" if tl["mad"][i] is None else f"{tl['mad'][i]:.4f}", int(tl["repeated"][i]),
                        int(tl["missed"][i]), int(tl["moving"][i])])
            prev = t
    files["windows_json"] = folder / "windows.json"
    files["windows_json"].write_text(json.dumps(tl["windows"]), encoding="utf-8")
    charts = make_charts(result, tl, folder / "charts")
    for k, p in charts.items():
        files[f"chart_{k}"] = p
    if report:
        from gameqa.fps_service.report_docx import build_report

        files["report_docx"] = build_report(result, charts, folder / "FPS_ANALYSIS_REPORT.docx")
    return files
