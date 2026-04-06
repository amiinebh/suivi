"""
FreightTrack Pro — PDF Export (v20)
Generates a professional shipment PDF with Incoterm section.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import io
from datetime import datetime

BRAND_RED   = colors.HexColor("#ff385c")
NEAR_BLACK  = colors.HexColor("#222222")
GRAY2       = colors.HexColor("#6a6a6a")
GRAY3       = colors.HexColor("#f2f2f2")
WHITE       = colors.white

INCOTERM_DESCRIPTIONS = {
    "EXW": "Ex Works — Seller makes goods available at their premises. Buyer bears all costs and risks.",
    "FCA": "Free Carrier — Seller delivers goods to a named carrier. Risk transfers at delivery point.",
    "CPT": "Carriage Paid To — Seller pays freight to destination. Risk transfers at first carrier.",
    "CIP": "Carriage & Insurance Paid — Seller pays freight + insurance. Risk at first carrier.",
    "DAP": "Delivered At Place — Seller delivers to named destination, uncleared for import.",
    "DPU": "Delivered At Place Unloaded — Seller delivers and unloads at destination.",
    "DDP": "Delivered Duty Paid — Seller bears all costs including import duties at destination.",
    "FAS": "Free Alongside Ship — Seller delivers goods alongside vessel at origin port.",
    "FOB": "Free On Board — Risk transfers when goods pass ship's rail at origin port.",
    "CFR": "Cost & Freight — Seller pays freight to destination port. Risk at origin port.",
    "CIF": "Cost, Insurance & Freight — Seller pays freight + insurance to destination port.",
}

def generate_shipment_pdf(shipment: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm)

    styles = getSampleStyleSheet()
    title_style   = ParagraphStyle('title',   fontName='Helvetica-Bold', fontSize=18, textColor=NEAR_BLACK, spaceAfter=2)
    sub_style     = ParagraphStyle('sub',     fontName='Helvetica',      fontSize=10, textColor=GRAY2)
    section_style = ParagraphStyle('section', fontName='Helvetica-Bold', fontSize=11, textColor=BRAND_RED, spaceBefore=14, spaceAfter=6)
    label_style   = ParagraphStyle('label',   fontName='Helvetica-Bold', fontSize=9,  textColor=GRAY2)
    value_style   = ParagraphStyle('value',   fontName='Helvetica',      fontSize=10, textColor=NEAR_BLACK)
    inco_style    = ParagraphStyle('inco',    fontName='Helvetica',      fontSize=9,  textColor=GRAY2, leading=14)

    s = shipment
    ref     = s.get('reference','—')
    inco    = s.get('incoterm','')
    inco_desc = INCOTERM_DESCRIPTIONS.get(inco, '')

    story = []

    # ── Header ──
    story.append(Paragraph("FreightTrack Pro", ParagraphStyle('brand', fontName='Helvetica-Bold', fontSize=10, textColor=BRAND_RED)))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Shipment — {ref}", title_style))
    story.append(Paragraph(f"Generated {datetime.now().strftime('%d %b %Y  %H:%M')}", sub_style))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_RED, spaceAfter=10))

    # ── Core details ──
    story.append(Paragraph("Shipment Details", section_style))
    fields = [
        ("Reference",    ref),
        ("Status",       s.get('status','—')),
        ("Client",       s.get('client','—')),
        ("Transport",    s.get('transport_mode','—')),
        ("Carrier",      s.get('carrier','—')),
        ("Origin (POL)", s.get('pol','—')),
        ("Destination (POD)", s.get('pod','—')),
        ("ETD",          str(s.get('etd','—'))),
        ("ETA",          str(s.get('eta','—'))),
        ("Containers",   str(s.get('containers','—'))),
        ("TEU",          str(s.get('teu','—'))),
        ("Commodity",    s.get('commodity','—')),
        ("Weight (kg)",  str(s.get('weight_kg','—'))),
        ("CBM",          str(s.get('cbm','—'))),
    ]
    tdata = []
    for i in range(0, len(fields), 2):
        row = []
        for j in range(2):
            if i+j < len(fields):
                k, v = fields[i+j]
                row += [Paragraph(k, label_style), Paragraph(v or '—', value_style)]
            else:
                row += [Paragraph('', label_style), Paragraph('', value_style)]
        tdata.append(row)

    t = Table(tdata, colWidths=[28*mm, 55*mm, 28*mm, 55*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), WHITE),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [WHITE, colors.HexColor("#f7f7f7")]),
        ('TEXTCOLOR',  (0,0), (-1,-1), NEAR_BLACK),
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),6),
        ('ROUNDEDCORNERS',[4]),
    ]))
    story.append(t)

    # ── Incoterm Section ──
    if inco:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Incoterm", section_style))
        inco_data = [[
            Paragraph(f"<b>{inco}</b>", ParagraphStyle('ib', fontName='Helvetica-Bold', fontSize=16, textColor=BRAND_RED)),
            Paragraph(inco_desc, inco_style)
        ]]
        it = Table(inco_data, colWidths=[22*mm, 148*mm])
        it.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#fff5f7")),
            ('LEFTPADDING',(0,0),(-1,-1),8),
            ('RIGHTPADDING',(0,0),(-1,-1),8),
            ('TOPPADDING', (0,0),(-1,-1),8),
            ('BOTTOMPADDING',(0,0),(-1,-1),8),
            ('ROUNDEDCORNERS',[8]),
            ('LINEBELOW',(0,0),(-1,-1),0.5,colors.HexColor("#ffb3c1")),
        ]))
        story.append(it)

    # ── Notes ──
    notes = s.get('notes','')
    if notes:
        story.append(Paragraph("Notes", section_style))
        story.append(Paragraph(notes, value_style))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e8e8e8")))
    story.append(Spacer(1, 4))
    story.append(Paragraph("FreightTrack Pro — Confidential", ParagraphStyle('footer', fontName='Helvetica', fontSize=8, textColor=GRAY2, alignment=TA_CENTER)))

    doc.build(story)
    return buf.getvalue()
