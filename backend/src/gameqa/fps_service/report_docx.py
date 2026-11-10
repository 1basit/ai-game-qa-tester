"""FPS_ANALYSIS_REPORT.docx — one Word report per analysed video (python-docx).

Contains only values produced by the analysis of that video: metadata, settings,
statistics, detected events, the three charts, the method and its limitations.
"""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401  (kept for future landscape tables)
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from gameqa.fps_service.analysis import FpsAnalysisResult

ACCENT = RGBColor(0x1D, 0x4E, 0xD8)
EVENT_FILL = {"freeze": "FEE4E2", "fps_drop": "FEF0C7", "stutter": "EBE9FE"}
EVENT_LABEL = {"freeze": "Freeze", "fps_drop": "FPS drop", "stutter": "Stutter"}


def _shade(cell, hex_fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _borders(table) -> None:
    """Explicit single-line borders (some viewers, e.g. macOS Quick Look, ignore table styles)."""
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:space"), "0"); e.set(qn("w:color"), "B9C0CC")
        b.append(e)
    tblPr.append(b)


def _table(doc, rows: list[tuple], header: tuple | None = None, widths: list[float] | None = None):
    n_cols = len(header or rows[0])
    t = doc.add_table(rows=0, cols=n_cols)
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(t)
    if header:
        cells = t.add_row().cells
        for c, h in zip(cells, header):
            c.text = str(h)
            c.paragraphs[0].runs[0].bold = True
            _shade(c, "E4E9F2")
    for r in rows:
        cells = t.add_row().cells
        for c, v in zip(cells, r):
            c.text = "—" if v is None else str(v)
        if not header:  # key/value table: shade and bold the key column
            _shade(cells[0], "F2F4F7")
            cells[0].paragraphs[0].runs[0].bold = True
    if widths:
        t.autofit = False
        for col, w in zip(t.columns, widths):
            col.width = Cm(w)
        for row in t.rows:
            for c, w in zip(row.cells, widths):
                c.width = Cm(w)
    for row in t.rows:
        for c in row.cells:
            for p in c.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9.5)
    return t


def _page_number_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Page ")
    run.font.size = Pt(8)
    for code in ("begin", None, "end"):
        r = p.add_run()
        r.font.size = Pt(8)
        if code == "begin":
            fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), "begin"); r._r.append(fc)
            it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = "PAGE"; r._r.append(it)
        elif code == "end":
            fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), "end"); r._r.append(fc)


def _note(doc, text: str) -> None:
    run = doc.add_paragraph().add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x47, 0x54, 0x67)


def _fmt_t(s: float) -> str:
    m = int(s // 60)
    return f"{m:02d}:{s - 60 * m:06.3f}"


def build_report(result: FpsAnalysisResult, charts: dict[str, Path], out_path: Path) -> Path:
    doc = Document()
    sec = doc.sections[0]
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(2.0))
    sec.top_margin = sec.bottom_margin = Cm(1.8)
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(10.5)
    _page_number_footer(sec)
    hdr = sec.header.paragraphs[0]
    hdr.text = "AI Game QA Tester — FPS Analysis Report"
    hdr.runs[0].font.size = Pt(8)
    hdr.runs[0].font.color.rgb = RGBColor(0x66, 0x70, 0x85)

    title = doc.add_heading("FPS Analysis Report", level=0)
    title.runs[0].font.color.rgb = ACCENT
    when = result.analysed_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    p = doc.add_paragraph()
    p.add_run(result.video_name).bold = True
    p.add_run(f"\nAnalysed {when} · {result.tool}")

    # 1 summary
    doc.add_heading("1. Summary", level=1)
    v = doc.add_paragraph()
    v.add_run(result.verdict).bold = True
    e, f, c, m = result.effective_fps, result.frame_times, result.counts, result.metadata
    _table(doc, [
        ("Target frame rate", f"{e['target_fps']:g} FPS (drop threshold {e['drop_threshold_fps']:g} FPS)"),
        ("Recording frame rate (nominal / average)", f"{m['nominal_fps']:g} / {m['average_fps']} FPS"),
        ("Effective FPS while moving (median / mean / minimum)", f"{e['median']} / {e['mean']} / {e['min']}"),
        ("1 % low FPS (from 99th-percentile frame time)", f"{f['one_percent_low_fps']} FPS"),
        ("Part of the video that could be measured", f"{e['measurable_fraction']:.0%}"),
        ("Freezes / FPS drops / stutter periods", f"{c['freezes']} / {c['fps_drops']} / {c['stutters']}"),
        ("Missed frames while moving", c["missed_frames_while_moving"]),
    ], widths=[8.5, 8.5])
    _note(doc, 
        "Effective FPS is the number of new pictures per second in the recording, measured only while "
        "the picture is moving. It is not the game's internal rendering FPS (see Section 8).")

    # 2 metadata
    doc.add_heading("2. Video", level=1)
    _table(doc, [
        ("File", m["file_name"]), ("Size", f"{m['file_size_mb']} MB"), ("Container / codec", f"{m['container']} / {m['codec']}"),
        ("Resolution", m["resolution"]), ("Duration", f"{m['duration_s']} s"), ("Frames", f"{m['frame_count']:,}"),
        ("Nominal FPS (declared by the file)", m["nominal_fps"]), ("Average FPS (from timestamps)", m["average_fps"]),
        ("Variable frame rate", "yes" if m["variable_frame_rate"] else "no (constant frame rate)"),
        ("Audio", "yes" if m["has_audio"] else "no"), ("Timestamp source", m["timestamp_source"]),
    ], widths=[6, 11])

    # 3 settings
    doc.add_heading("3. Analysis settings", level=1)
    s = result.settings
    _table(doc, [
        ("Target FPS", f"{s['target_fps']:g}"), ("FPS drop", f"effective FPS < {s['drop_ratio']:.0%} of target in ≥ 2 consecutive 1 s windows"),
        ("Freeze", f"one picture held ≥ {s['freeze_ms']:g} ms while the scene is moving"),
        ("Stutter", f"≥ {s['stutter_min_missed']} isolated missed frames in a 1 s window, above the drop threshold, ≥ 2 windows"),
    ], widths=[4, 13])

    # 4 frame timing
    doc.add_heading("4. Frame presentation timing", level=1)
    i = result.frame_intervals
    _table(doc, [("Expected interval (1 / nominal FPS)", f"{i['expected_ms']} ms"), ("Median interval", f"{i['median_ms']} ms"),
                 ("Minimum / maximum interval", f"{i['min_ms']} / {i['max_ms']} ms"), ("99th percentile", f"{i['p99_ms']} ms"),
                 ("Irregular intervals (> 25 % from the median)", i["irregular_intervals"])], widths=[8.5, 8.5])
    doc.add_paragraph("In a constant-frame-rate recording every interval is the same even when the game "
                      "slowed down: the recorder repeats the last picture instead. Those repeats are analysed in Section 5.")
    if "frame_intervals" in charts:
        doc.add_picture(str(charts["frame_intervals"]), width=Cm(17))

    # 5 effective fps and frame times
    doc.add_heading("5. Effective frame rate and frame times", level=1)
    _table(doc, [("Effective FPS — median / mean", f"{e['median']} / {e['mean']}"), ("Effective FPS — minimum / 5th percentile", f"{e['min']} / {e['p5']}"),
                 ("Frame time — median / 95th / 99th percentile", f"{f['p50_ms']} / {f['p95_ms']} / {f['p99_ms']} ms"),
                 ("Longest frame time", f"{f['max_ms']} ms"), ("Frame times measured", f"{f['count']:,}")], widths=[8.5, 8.5])
    if "effective_fps" in charts:
        doc.add_picture(str(charts["effective_fps"]), width=Cm(17))
    if "frame_changes" in charts:
        doc.add_picture(str(charts["frame_changes"]), width=Cm(17))
    _note(doc, "Shaded bands mark detected events: red = freeze, orange = FPS drop, purple = stutter.")

    # 6 events
    doc.add_heading("6. Detected events", level=1)
    if not result.events:
        doc.add_paragraph("No freezes, FPS drops or stutter periods were detected in the measurable part of the video.")
    else:
        t = _table(doc, [(EVENT_LABEL[ev.type], _fmt_t(ev.start_s), _fmt_t(ev.end_s), f"{ev.duration_s:.2f} s", ev.description)
                         for ev in result.events], header=("Type", "Start", "End", "Duration", "Description"),
                   widths=[2.2, 2.2, 2.2, 2.0, 8.4])
        for row, ev in zip(t.rows[1:], result.events):
            _shade(row.cells[0], EVENT_FILL[ev.type])
    _note(doc, "Each event should be confirmed by watching the video at that time: video-editing cuts and "
                      "intentional pauses can look like freezes.")

    # 7 method
    doc.add_heading("7. How this was measured", level=1)
    for line in [
        "Average FPS = (N − 1) / (t_last − t_first), from the frame presentation timestamps t of the N frames.",
        "Frame interval Δtᵢ = tᵢ − tᵢ₋₁; expected interval = 1 / nominal FPS.",
        "Repeated frame: mean absolute difference MADᵢ = mean|Gᵢ − Gᵢ₋₁| of 160×90 greyscale frames < 0.25 grey levels.",
        "Missed render: a repeated frame (or a longer interval in variable-frame-rate files) while the frames just "
        "before and after are clearly moving (MAD ≥ 1.0 for at least 3 nearby frames).",
        "Effective FPS = new pictures in a 1 s window ÷ 1 s, computed every 0.25 s over moving windows only.",
        "1 % low FPS = 1 ÷ (99th percentile of the time each new picture stayed on screen).",
    ]:
        doc.add_paragraph(line, style="List Bullet")

    # 8 limitations
    doc.add_heading("8. Limitations", level=1)
    for line in result.limitations:
        doc.add_paragraph(line, style="List Bullet")
    if result.warnings:
        doc.add_heading("Warnings for this video", level=2)
        for w in result.warnings:
            doc.add_paragraph(w, style="List Bullet")

    # 9 processing
    doc.add_heading("9. Processing", level=1)
    pr = result.processing
    _table(doc, [("Processing time", f"{pr['seconds']} s ({pr['realtime_factor']}× real time)"), ("Engine", pr["engine"]),
                 ("Source file", result.video_path)], widths=[4, 13])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
