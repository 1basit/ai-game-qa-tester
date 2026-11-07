"""Bug-report export (FR-6): JSON for other tools, PDF for the team (ReportLab).

ReportLab rather than WeasyPrint: pure Python, no system libraries (Pango/Cairo).
"""

from __future__ import annotations

import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

CATEGORIES = ["npc_anomaly", "texture_pop_in", "fps_drop", "animation_glitch", "collision_clipping"]
CATEGORY_LABEL = {"npc_anomaly": "NPC anomaly", "texture_pop_in": "Texture pop-in", "fps_drop": "FPS drop / freeze",
                  "animation_glitch": "Animation glitch", "collision_clipping": "Collision / clipping"}
SEVERITIES = ["high", "medium", "low"]
SEV_COLOUR = {"high": colors.HexColor("#b42318"), "medium": colors.HexColor("#b54708"),
              "low": colors.HexColor("#027a48")}


def summary(detections: list[dict]) -> dict:
    by_cat = Counter(d["category"] for d in detections)
    by_sev = Counter(d.get("severity") or "unrated" for d in detections)
    matrix = {c: {s: 0 for s in SEVERITIES} for c in CATEGORIES}
    for d in detections:
        if d.get("severity") in SEVERITIES:
            matrix[d["category"]][d["severity"]] += 1
    return {"total": len(detections), "by_category": {c: by_cat.get(c, 0) for c in CATEGORIES},
            "by_severity": {s: by_sev.get(s, 0) for s in SEVERITIES}, "matrix": matrix}


def build_json(meta: dict, detections: list[dict]) -> dict:
    """Detection records, timestamps, severity levels and evidence references (FR-6)."""
    return {
        "report_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **meta,
        "summary": summary(detections),
        "detections": [{k: v for k, v in d.items() if k != "media"} for d in detections],
        "notes": ["Times are seconds from the first frame of the uploaded video.",
                  "Evidence paths are relative to the evidence store and are served by the API to project members."],
    }


def _utc(t) -> str:
    if isinstance(t, datetime):
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(t or "")


def _fmt_t(s: float) -> str:
    m, sec = divmod(s, 60)
    return f"{int(m):02d}:{sec:06.3f}"


def _chart(s: dict) -> Drawing:
    d = Drawing(170 * mm, 60 * mm)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 15 * mm, 12 * mm, 150 * mm, 42 * mm
    ch.data = [[s["matrix"][c][sev] for c in CATEGORIES] for sev in SEVERITIES]
    ch.categoryAxis.categoryNames = [CATEGORY_LABEL[c] for c in CATEGORIES]
    ch.categoryAxis.labels.fontSize = 7
    ch.valueAxis.valueMin = 0
    ch.valueAxis.labels.fontSize = 7
    for i, sev in enumerate(SEVERITIES):
        ch.bars[i].fillColor = SEV_COLOUR[sev]
    d.add(ch)
    for i, sev in enumerate(SEVERITIES):
        d.add(String(15 * mm + i * 30 * mm, 2 * mm, f"■ {sev.title()}", fontSize=8, fillColor=SEV_COLOUR[sev]))
    return d


def _thumb(src: Path, tmp: Path, width_px: int = 640) -> Path | None:
    img = cv2.imread(str(src))
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > width_px:
        img = cv2.resize(img, (width_px, int(h * width_px / w)), interpolation=cv2.INTER_AREA)
    out = tmp / (src.stem + ".jpg")
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


def build_pdf(out_path: Path, meta: dict, detections: list[dict], evidence_root: Path) -> Path:
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=8, leading=10)
    s = summary(detections)
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=f"Bug report — {meta.get('video', '')}")
    story: list[Any] = [Paragraph("AI Game QA Tester — Bug Report", styles["Title"])]
    rows = [["Project", meta.get("project", "")], ["Game build", meta.get("game_build", "")],
            ["Video", meta.get("video", "")], ["Duration", f"{meta.get('duration_s') or 0:.1f} s"],
            ["Job", meta.get("job_id", "")], ["Status", meta.get("status", "")],
            ["Analysed", _utc(meta.get("finished_at"))],
            ["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")]]
    t = Table(rows, colWidths=[35 * mm, 145 * mm])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (0, -1), colors.grey)]))
    story += [t, Spacer(1, 6 * mm), Paragraph("Summary", styles["Heading2"])]
    head = ["Category"] + [x.title() for x in SEVERITIES] + ["Total"]
    body = [[CATEGORY_LABEL[c]] + [s["matrix"][c][x] for x in SEVERITIES] + [s["by_category"][c]] for c in CATEGORIES]
    body.append(["All"] + [s["by_severity"][x] for x in SEVERITIES] + [s["total"]])
    st = Table([head] + body, colWidths=[55 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm])
    st.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaecf0")),
                            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0d5dd")),
                            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
    story += [st, Spacer(1, 4 * mm), _chart(s)]
    if meta.get("warnings"):
        story += [Paragraph("Warnings", styles["Heading3"])] + [Paragraph(w, small) for w in meta["warnings"]]
    story += [PageBreak(), Paragraph(f"Detections ({len(detections)})", styles["Heading2"])]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for i, d in enumerate(detections, 1):
            ev = d.get("evidence") or {}
            shot = (d.get("metrics") or {}).get("screenshot_marked") or ev.get("screenshot_path")
            img = None
            if shot and (evidence_root / shot).exists():
                th = _thumb(evidence_root / shot, tmp)
                if th:
                    img = Image(str(th), width=80 * mm, height=45 * mm, kind="proportional")
            sev = d.get("severity") or "unrated"
            text = [
                Paragraph(f"<b>#{i} {CATEGORY_LABEL.get(d['category'], d['category'])} — {d['subtype']}</b>",
                          styles["BodyText"]),
                Paragraph(f"<font color='{SEV_COLOUR.get(sev, colors.grey).hexval()}'><b>{sev.upper()}</b></font> "
                          f"— {d.get('severity_reason') or ''}", small),
                Paragraph(f"Time {_fmt_t(d['start_time_s'])} – {_fmt_t(d['end_time_s'])} "
                          f"(frames {d['start_frame']}–{d['end_frame']}), confidence {d['confidence']:.2f}", small),
                Paragraph(d.get("description") or "", small),
                Paragraph(f"Detector {d['detector']} v{d['detector_version']}"
                          + (f"; clip {ev.get('clip_path')}" if ev.get("clip_path") else ""), small),
            ]
            row = Table([[img or Paragraph("(no screenshot)", small), text]], colWidths=[85 * mm, 95 * mm])
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                     ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0d5dd"))]))
            story.append(KeepTogether([row, Spacer(1, 3 * mm)]))
        doc.build(story)
    return out_path
