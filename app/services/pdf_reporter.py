# ─────────────────────────────────────────────────────────────────────────────
# AUDITIQ — PDF AUDIT REPORT GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
#
# Generates a professional, stakeholder-ready PDF report from the final
# audit result dict. Uses ReportLab Platypus for structured multi-page layout.
#
# Design:
#   - Dark navy header bar with AuditIQ branding
#   - Large PASS / FAIL verdict banner (green / red)
#   - Score badge, account facts, timestamp
#   - Pre-detection findings table
#   - AI reasoning section
#   - Grader rubric scores table
#   - Retrieved legal rules summary
#   - Full labeled transcript
#   - Footer with page numbers
# ─────────────────────────────────────────────────────────────────────────────

import os
import io
from datetime  import datetime, timezone
from typing    import Dict, Any

from reportlab.lib.pagesizes   import A4
from reportlab.lib.units       import mm
from reportlab.lib.styles      import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums       import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib             import colors
from reportlab.platypus        import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.platypus.flowables import Flowable

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR PALETTE (matches AuditIQ frontend)
# ─────────────────────────────────────────────────────────────────────────────

C_NAVY       = colors.HexColor("#0A0F1E")
C_CARD       = colors.HexColor("#111827")
C_PANEL      = colors.HexColor("#1E293B")
C_PASS       = colors.HexColor("#10B981")
C_FAIL       = colors.HexColor("#EF4444")
C_WARN       = colors.HexColor("#F59E0B")
C_ACCENT     = colors.HexColor("#6366F1")
C_TEXT       = colors.HexColor("#F1F5F9")
C_MUTED      = colors.HexColor("#94A3B8")
C_BORDER     = colors.HexColor("#2D3748")
C_WHITE      = colors.white
C_LIGHT_GRAY = colors.HexColor("#F8FAFC")
C_PASS_BG    = colors.HexColor("#ECFDF5")
C_FAIL_BG    = colors.HexColor("#FEF2F2")
C_WARN_BG    = colors.HexColor("#FFFBEB")
C_ACCENT_BG  = colors.HexColor("#EEF2FF")

# ─────────────────────────────────────────────────────────────────────────────
# STYLE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

def _build_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle(
        "AQTitle", fontSize=22, fontName="Helvetica-Bold",
        textColor=C_WHITE, alignment=TA_LEFT, leading=26,
    )
    styles["subtitle"] = ParagraphStyle(
        "AQSubtitle", fontSize=10, fontName="Helvetica",
        textColor=C_MUTED, alignment=TA_LEFT, leading=14,
    )
    styles["section_header"] = ParagraphStyle(
        "AQSectionHeader", fontSize=11, fontName="Helvetica-Bold",
        textColor=C_NAVY, spaceBefore=10, spaceAfter=4, leading=14,
    )
    styles["body"] = ParagraphStyle(
        "AQBody", fontSize=9, fontName="Helvetica",
        textColor=C_CARD, leading=14, spaceAfter=4,
    )
    styles["body_muted"] = ParagraphStyle(
        "AQBodyMuted", fontSize=8, fontName="Helvetica",
        textColor=colors.HexColor("#64748B"), leading=12,
    )
    styles["mono"] = ParagraphStyle(
        "AQMono", fontSize=8, fontName="Courier",
        textColor=C_CARD, leading=12, spaceAfter=2,
    )
    styles["mono_muted"] = ParagraphStyle(
        "AQMonoMuted", fontSize=8, fontName="Courier",
        textColor=colors.HexColor("#64748B"), leading=12,
    )
    styles["verdict_pass"] = ParagraphStyle(
        "AQVerdictPass", fontSize=28, fontName="Helvetica-Bold",
        textColor=C_PASS, alignment=TA_CENTER, leading=34,
    )
    styles["verdict_fail"] = ParagraphStyle(
        "AQVerdictFail", fontSize=28, fontName="Helvetica-Bold",
        textColor=C_FAIL, alignment=TA_CENTER, leading=34,
    )
    styles["score"] = ParagraphStyle(
        "AQScore", fontSize=40, fontName="Helvetica-Bold",
        textColor=C_ACCENT, alignment=TA_CENTER, leading=48,
    )
    styles["label"] = ParagraphStyle(
        "AQLabel", fontSize=7, fontName="Helvetica-Bold",
        textColor=C_MUTED, alignment=TA_CENTER,
        leading=10, spaceAfter=2,
        letterSpacing=1,
    )
    styles["tag"] = ParagraphStyle(
        "AQTag", fontSize=8, fontName="Helvetica-Bold",
        textColor=C_ACCENT, leading=10,
    )
    styles["reasoning"] = ParagraphStyle(
        "AQReasoning", fontSize=9, fontName="Helvetica",
        textColor=C_CARD, leading=15, spaceAfter=4,
        leftIndent=6,
    )
    styles["transcript_agent"] = ParagraphStyle(
        "AQTranscriptAgent", fontSize=8, fontName="Helvetica-Bold",
        textColor=C_NAVY, leading=12,
    )
    styles["transcript_debtor"] = ParagraphStyle(
        "AQTranscriptDebtor", fontSize=8, fontName="Helvetica",
        textColor=colors.HexColor("#374151"), leading=12,
    )
    styles["transcript_unknown"] = ParagraphStyle(
        "AQTranscriptUnknown", fontSize=8, fontName="Helvetica",
        textColor=colors.HexColor("#9CA3AF"), leading=12,
    )
    styles["footer"] = ParagraphStyle(
        "AQFooter", fontSize=7, fontName="Helvetica",
        textColor=C_MUTED, alignment=TA_CENTER, leading=10,
    )
    return styles

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM FLOWABLES
# ─────────────────────────────────────────────────────────────────────────────

class ColorBar(Flowable):
    """Full-width solid colour bar — used for header and section dividers."""
    def __init__(self, width, height, color, radius=0):
        super().__init__()
        self.bar_w  = width
        self.bar_h  = height
        self.color  = color
        self.radius = radius

    def wrap(self, *args): return self.bar_w, self.bar_h
    def draw(self):
        self.canv.setFillColor(self.color)
        if self.radius:
            self.canv.roundRect(0, 0, self.bar_w, self.bar_h, self.radius, fill=1, stroke=0)
        else:
            self.canv.rect(0, 0, self.bar_w, self.bar_h, fill=1, stroke=0)


class VerdictBanner(Flowable):
    """Large coloured verdict + score banner."""
    def __init__(self, width, passed, score, verifier_rejected=False):
        super().__init__()
        self.bar_w   = width
        self.passed  = passed
        self.score   = score
        self.rejected= verifier_rejected

    def wrap(self, *args): return self.bar_w, 72

    def draw(self):
        c    = self.canv
        w, h = self.bar_w, 72
        fg   = C_PASS    if self.passed else C_FAIL
        label= "COMPLIANT" if self.passed else "VIOLATION DETECTED"

        # Clean white background with a subtle gray border
        c.setFillColor(C_WHITE)
        c.setStrokeColor(colors.HexColor("#E2E8F0")) # Light gray border
        c.roundRect(0, 0, w, h, 6, fill=1, stroke=1)

        # Keep the sharp left accent bar (Green or Red)
        c.setFillColor(fg)
        c.roundRect(0, 0, 6, h, 3, fill=1, stroke=0)

        # Verdict text (Navy instead of bright colored text)
        c.setFillColor(C_NAVY)
        c.setFont("Helvetica-Bold", 20)
        icon = "✓" if self.passed else "✗"
        c.drawString(20, h - 40, f"{icon}  {label}")

        # Minimalist Score Badge
        badge_x = w - 80
        c.setFillColor(fg) # Score number is colored
        c.setFont("Helvetica-Bold", 28)
        c.drawCentredString(badge_x + 30, h - 35, f"{str(self.score)}")
        
        c.setFillColor(C_MUTED)
        c.setFont("Helvetica", 9)
        c.drawCentredString(badge_x + 30, 15, "/ 10 Score")

        # Verifier override note
        if self.rejected:
            c.setFillColor(C_WARN)
            c.setFont("Helvetica-Bold", 7)
            c.drawString(20, 10, "⚡ GRADER OVERRIDE APPLIED")

# ─────────────────────────────────────────────────────────────────────────────
# PAGE TEMPLATE (header + footer on every page)
# ─────────────────────────────────────────────────────────────────────────────

def _build_page_template(account_name: str, timestamp: str):
    def on_page(canvas, doc):
        W, H = A4
        m    = 15 * mm

        # Top thin accent line
        canvas.saveState()
        canvas.setFillColor(C_ACCENT)
        canvas.rect(m, H - 10*mm, W - 2*m, 2, fill=1, stroke=0)

        # Header text
        canvas.setFillColor(C_MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(m, H - 9*mm, "AuditIQ — FDCPA Compliance Audit Report")
        canvas.drawRightString(W - m, H - 9*mm, f"{account_name}  |  {timestamp}")

        # Footer line
        canvas.setFillColor(C_BORDER)
        canvas.rect(m, 12*mm, W - 2*m, 0.5, fill=1, stroke=0)
        canvas.setFillColor(C_MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(W / 2, 8*mm, f"Page {doc.page}  —  CONFIDENTIAL")
        canvas.restoreState()

    return on_page

# ─────────────────────────────────────────────────────────────────────────────
# SECTION BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def _section_divider(styles, title: str) -> list:
    return [
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1, color=C_BORDER, spaceAfter=4),
        Paragraph(title.upper(), styles["section_header"]),
        Spacer(1, 2),
    ]


def _key_value_table(rows: list, col_widths=None) -> Table:
    """Two-column label/value table for account facts etc."""
    if col_widths is None:
        col_widths = [55*mm, 105*mm]
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",    (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR",   (0, 0), (0, -1), C_MUTED),
        ("TEXTCOLOR",   (1, 0), (1, -1), C_CARD),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_LIGHT_GRAY, C_WHITE]),
        ("GRID",        (0, 0), (-1, -1), 0.25, C_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _violations_table(violations: list, styles) -> list:
    if not violations:
        return [Paragraph("No violations found.", styles["body_muted"])]
    rows = [["Rule ID", "Status"]]
    for v in violations:
        rows.append([Paragraph(v, styles["mono"]), Paragraph("VIOLATION", styles["tag"])])
    t = Table(rows, colWidths=[130*mm, 30*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), C_NAVY),
        ("TEXTCOLOR",   (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("TOPPADDING",  (0,0), (-1,-1), 5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_FAIL_BG, C_WHITE]),
        ("GRID",        (0,0),(-1,-1), 0.25, C_BORDER),
        ("LEFTPADDING", (0,0),(-1,-1), 8),
        ("ALIGN",       (1,0),(-1,-1), "CENTER"),
    ]))
    return [t]


def _pre_detection_table(pre: dict, styles) -> list:
    confirmed  = pre.get("confirmed_violations", [])
    suspicious = pre.get("suspicious_patterns", [])
    mm_ok      = pre.get("mini_miranda_detected", False)
    mm_ev      = pre.get("mini_miranda_evidence", "")
    risk       = pre.get("risk_score", 0)

    elements = []

    # Mini-Miranda status row
    mm_color = C_PASS if mm_ok else C_FAIL
    mm_text  = f"DETECTED — \"{mm_ev}\"" if mm_ok else "NOT DETECTED — Omission violation"
    mm_rows  = [
        ["Mini-Miranda (§ 807(11))",
         Paragraph(mm_text, ParagraphStyle("mm", fontSize=8,
             textColor=mm_color, fontName="Helvetica-Bold", leading=11))],
        ["Pre-Detection Risk Score", f"{risk}/10"],
    ]
    elements.append(_key_value_table(mm_rows))
    elements.append(Spacer(1, 6))

    # Confirmed violations
    if confirmed:
        elements.append(Paragraph("Confirmed Violations (Deterministic)", styles["body"]))
        rows = [["Rule ID", "Citation", "Confidence", "Evidence"]]
        for v in confirmed:
            ev_text = " | ".join(v.get("evidence", [])[:2])
            if len(ev_text) > 120:
                ev_text = ev_text[:120] + "..."
            rows.append([
                Paragraph(v["rule_id"], styles["mono"]),
                v.get("citation", ""),
                v.get("confidence", "").upper(),
                Paragraph(ev_text, styles["mono_muted"]),
            ])
        t = Table(rows, colWidths=[50*mm, 22*mm, 20*mm, 68*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,0), C_FAIL),
            ("TEXTCOLOR",   (0,0),(-1,0), C_WHITE),
            ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",    (0,0),(-1,-1), 7.5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 4),
            ("TOPPADDING",  (0,0),(-1,-1), 4),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_FAIL_BG, C_WHITE]),
            ("GRID",        (0,0),(-1,-1), 0.25, C_BORDER),
            ("LEFTPADDING", (0,0),(-1,-1), 6),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 4))

    # Suspicious patterns
    if suspicious:
        elements.append(Paragraph("Suspicious Patterns (Requires LLM Judgment)", styles["body"]))
        rows = [["Rule ID", "Citation", "What Was Flagged"]]
        for v in suspicious:
            rows.append([
                Paragraph(v["rule_id"], styles["mono"]),
                v.get("citation", ""),
                Paragraph(v.get("explanation", "")[:100], styles["mono_muted"]),
            ])
        t = Table(rows, colWidths=[50*mm, 22*mm, 88*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,0), C_WARN),
            ("TEXTCOLOR",   (0,0),(-1,0), C_WHITE),
            ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",    (0,0),(-1,-1), 7.5),
            ("BOTTOMPADDING",(0,0),(-1,-1), 4),
            ("TOPPADDING",  (0,0),(-1,-1), 4),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_WARN_BG, C_WHITE]),
            ("GRID",        (0,0),(-1,-1), 0.25, C_BORDER),
            ("LEFTPADDING", (0,0),(-1,-1), 6),
        ]))
        elements.append(t)

    if not confirmed and not suspicious:
        elements.append(Paragraph("No violations or suspicious patterns detected by pre-detection layer.", styles["body_muted"]))

    return elements


def _grade_report_table(grade: dict, styles) -> list:
    if not grade:
        return [Paragraph("Grade report not available.", styles["body_muted"])]

    rubric = grade.get("rubric_scores", grade)  # handle both nested and flat
    total  = grade.get("total_grade", "N/A")

    criteria = [
        ("Mini-Miranda Handling",  rubric.get("mini_miranda_handling",  "—"), 2),
        ("Pre-Detection Coverage", rubric.get("pre_detection_coverage", "—"), 3),
        ("Legal Grounding",        rubric.get("legal_grounding",        "—"), 2),
        ("Violation ID Accuracy",  rubric.get("violation_id_accuracy",  "—"), 2),
        ("Score Calibration",      rubric.get("score_calibration",      "—"), 1),
    ]

    rows = [["Criterion", "Score", "Max", "Result"]]
    for name, score, max_pts in criteria:
        try:
            pct    = int(score) / max_pts
            result = "PASS" if pct >= 0.67 else "PARTIAL" if pct > 0 else "FAIL"
            color  = C_PASS if pct >= 0.67 else C_WARN if pct > 0 else C_FAIL
        except (TypeError, ValueError, ZeroDivisionError):
            result, color = "—", C_MUTED
        rows.append([
            name,
            str(score),
            str(max_pts),
            Paragraph(result, ParagraphStyle("gr", fontSize=8, fontName="Helvetica-Bold",
                textColor=color, alignment=TA_CENTER, leading=10)),
        ])
    # Total row
    rows.append(["TOTAL GRADE", str(total), "10", ""])

    t = Table(rows, colWidths=[100*mm, 20*mm, 20*mm, 20*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(-1,0), C_NAVY),
        ("TEXTCOLOR",   (0,0),(-1,0), C_WHITE),
        ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
        ("BACKGROUND",  (0,-1),(-1,-1), C_ACCENT_BG),
        ("FONTNAME",    (0,-1),(-1,-1), "Helvetica-Bold"),
        ("FONTSIZE",    (0,0),(-1,-1), 8.5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("TOPPADDING",  (0,0),(-1,-1), 5),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[C_LIGHT_GRAY, C_WHITE]),
        ("GRID",        (0,0),(-1,-1), 0.25, C_BORDER),
        ("ALIGN",       (1,0),(-1,-1), "CENTER"),
        ("LEFTPADDING", (0,0),(-1,-1), 8),
    ]))
    elements = [t]

    suggestion = grade.get("prompt_improvement_suggestion", "")
    if suggestion:
        elements += [
            Spacer(1, 6),
            Paragraph("Prompt Improvement Suggestion:", styles["body"]),
            Paragraph(suggestion, styles["reasoning"]),
        ]

    hallucinations = grade.get("hallucinations_found", [])
    if hallucinations:
        elements += [
            Spacer(1, 4),
            Paragraph("Hallucinations Detected:", styles["body"]),
        ]
        for h in hallucinations:
            elements.append(Paragraph(f"• {h}", styles["body_muted"]))

    return elements


def _transcript_section(formatted_transcript: str, styles) -> list:
    if not formatted_transcript:
        return [Paragraph("No transcript available.", styles["body_muted"])]

    elements = []
    for line in formatted_transcript.strip().split("\n"):
        line = line.strip()
        if not line:
            elements.append(Spacer(1, 3))
            continue
        if line.startswith("[AGENT]"):
            text = line[7:].strip()
            elements.append(
                Paragraph(f"<b>[AGENT]</b> {text}", styles["transcript_agent"])
            )
        elif line.startswith("[DEBTOR]"):
            text = line[8:].strip()
            elements.append(
                Paragraph(f"[DEBTOR] {text}", styles["transcript_debtor"])
            )
        else:
            elements.append(Paragraph(line, styles["transcript_unknown"]))
        elements.append(Spacer(1, 2))

    return elements

# ─────────────────────────────────────────────────────────────────────────────
# MAIN REPORT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def generate_audit_pdf(result: Dict[str, Any], output_path: str = None) -> bytes:
    """
    Generates a PDF audit report from the final result dict.

    Args:
        result:      The complete result dict from run_qa_audit()
        output_path: Optional path to save the PDF. If None, returns bytes only.

    Returns:
        PDF as bytes (can be streamed directly to HTTP response).
    """
    styles = _build_styles()
    buffer = io.BytesIO()

    # ── Page setup ────────────────────────────────────────────────────────────
    PAGE_W, PAGE_H = A4
    MARGIN         = 15 * mm
    CONTENT_W      = PAGE_W - 2 * MARGIN

    account_name  = str(result.get("account_name") or "Unknown Account")
    now_utc       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    compliance    = bool(result.get("compliance_passed", False))
    score         = result.get("performance_score") or 0
    reasoning     = str(result.get("reasoning") or "No reasoning provided.")
    violations    = result.get("violations_found") or []
    v_notes       = str(result.get("verification_notes") or "")
    sql_facts     = str(result.get("sql_facts") or "N/A")
    retrieved     = result.get("retrieved_rules") or []
    pre           = result.get("pre_detection") or {}
    grade         = result.get("grade_report") or {}
    transcript_raw= result.get("formatted_transcript") or result.get("transcript") or "No transcript available."
    fmt_transcript= str(transcript_raw)
    seg           = result.get("speaker_segmentation") or {}
    verifier_rej  = reasoning.startswith("[OVERRIDDEN BY GRADER]") or \
                    reasoning.startswith("[PRE-DETECTOR OVERRIDE]")

    doc = SimpleDocTemplate(
        buffer,
        pagesize   = A4,
        leftMargin = MARGIN, rightMargin = MARGIN,
        topMargin  = 22 * mm, bottomMargin = 20 * mm,
        title      = f"AuditIQ Report — {account_name}",
        author     = "AuditIQ FDCPA Compliance Engine",
    )

    on_page = _build_page_template(account_name, now_utc)
    story   = []

    # ── COVER HEADER ──────────────────────────────────────────────────────────
    story.append(Paragraph("<b>AuditIQ</b>", ParagraphStyle(
        "CleanTitle", fontSize=26, fontName="Helvetica-Bold", textColor=C_NAVY, leading=30
    )))
    story.append(Spacer(1, 4))
    story.append(Paragraph("FDCPA Compliance Audit Report", ParagraphStyle(
        "CleanSub", fontSize=11, fontName="Helvetica", textColor=C_MUTED, leading=14
    )))
    story.append(Spacer(1, 12))
    # Sleek 2px indigo accent line to anchor the header
    story.append(HRFlowable(width="100%", thickness=2, color=C_ACCENT, spaceAfter=24))

    # ── VERDICT BANNER ────────────────────────────────────────────────────────
    story.append(VerdictBanner(CONTENT_W, compliance, score, verifier_rej))
    story.append(Spacer(1, 10))

    # ── ACCOUNT FACTS ─────────────────────────────────────────────────────────
    story += _section_divider(styles, "Account Information")
    facts_rows = [
        ["Account Name",    account_name],
        ["SQL Facts",       sql_facts],
        ["Report Generated",now_utc],
        ["Speaker Seg. Confidence",
         f"{seg.get('confidence', 0):.0%} — "
         f"{seg.get('agent_turns', '?')} agent turns, "
         f"{seg.get('debtor_turns', '?')} debtor turns"],
    ]
    story.append(_key_value_table(facts_rows))
    story.append(Spacer(1, 8))

    # ── VIOLATIONS FOUND ──────────────────────────────────────────────────────
    story += _section_divider(styles, f"Violations Found ({len(violations)})")
    story += _violations_table(violations, styles)
    story.append(Spacer(1, 8))

    # ── PRE-DETECTION LAYER ───────────────────────────────────────────────────
    story += _section_divider(styles, "Pre-Detection Layer (Deterministic Analysis)")
    story += _pre_detection_table(pre, styles)
    story.append(Spacer(1, 8))

    # ── AI REASONING ─────────────────────────────────────────────────────────
    story += _section_divider(styles, "AI Auditor Reasoning")

    if verifier_rej:
        story.append(
            Paragraph(
                "⚡ Note: This reasoning was overridden by the Prompt Grader.",
                ParagraphStyle("warn", fontSize=8, fontName="Helvetica-Bold",
                    textColor=C_WARN, leading=12, spaceAfter=6)
            )
        )

    # Split reasoning into paragraphs for better readability
    for para in reasoning.split("\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para, styles["reasoning"]))

    story.append(Spacer(1, 6))
    story.append(Paragraph("Grader / Verification Notes:", styles["body"]))
    story.append(Paragraph(v_notes or "N/A", styles["body_muted"]))
    story.append(Spacer(1, 8))

    # ── PROMPT GRADE REPORT ───────────────────────────────────────────────────
    story += _section_divider(styles, "Prompt Grade Report (Audit Quality Evaluation)")
    story += _grade_report_table(grade, styles)
    story.append(Spacer(1, 8))

    # ── RETRIEVED LEGAL RULES ─────────────────────────────────────────────────
    story += _section_divider(styles, f"Retrieved FDCPA Rules ({len(retrieved)})")
    if retrieved:
        rule_rows = [["Rule ID", "Retrieved"]]
        for rid in retrieved:
            rule_rows.append([Paragraph(rid, styles["mono"]), "Yes"])
        t = Table(rule_rows, colWidths=[140*mm, 20*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,0), C_NAVY),
            ("TEXTCOLOR",   (0,0),(-1,0), C_WHITE),
            ("FONTNAME",    (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",    (0,0),(-1,-1), 8),
            ("BOTTOMPADDING",(0,0),(-1,-1), 4),
            ("TOPPADDING",  (0,0),(-1,-1), 4),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[C_ACCENT_BG, C_WHITE]),
            ("GRID",        (0,0),(-1,-1), 0.25, C_BORDER),
            ("LEFTPADDING", (0,0),(-1,-1), 8),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No rules retrieved.", styles["body_muted"]))

    story.append(PageBreak())

    # ── TRANSCRIPT (NEW PAGE) ─────────────────────────────────────────────────
    story += _section_divider(styles, "Full Call Transcript (Speaker-Attributed)")
    story.append(
        Paragraph(
            "<b>[AGENT]</b> = debt collector  |  [DEBTOR] = consumer  |  [UNKNOWN] = unattributed",
            styles["body_muted"]
        )
    )
    story.append(Spacer(1, 6))
    story += _transcript_section(fmt_transcript, styles)

    # ── BUILD ─────────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    if output_path:
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)
        import logging
        logging.getLogger("pdf_reporter").info(f"PDF saved: {output_path}")

    return pdf_bytes