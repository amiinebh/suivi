"""
PDF generation for shipment reports and dashboard summaries.
Uses ReportLab for professional PDF generation.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from io import BytesIO
from datetime import datetime

def generate_shipment_pdf(shipment):
    """Generate PDF report for a single shipment."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    story = []

    # Header
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#0a0f1e'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    story.append(Paragraph("FreightTrack Pro", title_style))
    story.append(Paragraph("Shipment Report", styles['Heading2']))
    story.append(Spacer(1, 0.3*inch))

    # Shipment Info Table
    data = [
        ['Reference:', shipment.ref or '—'],
        ['Quotation #:', shipment.quotation_number or '—'],
        ['Container/AWB:', shipment.ref2 or '—'],
        ['Booking No:', shipment.booking_no or '—'],
        ['Mode:', shipment.mode or '—'],
        ['Carrier:', shipment.carrier or '—'],
        ['Vessel:', shipment.vessel or '—'],
        ['Status:', shipment.status or '—'],
    ]

    info_table = Table(data, colWidths=[2*inch, 4*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f4ff')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#0a0f1e')),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d8f0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.3*inch))

    # Route
    story.append(Paragraph("<b>Route</b>", styles['Heading3']))
    route_data = [
        ['Origin (POL):', shipment.pol or '—'],
        ['Destination (POD):', shipment.pod or '—'],
        ['ETD:', shipment.etd or '—'],
        ['ETA:', shipment.eta or '—'],
    ]
    route_table = Table(route_data, colWidths=[2*inch, 4*inch])
    route_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f4ff')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#0a0f1e')),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(route_table)
    story.append(Spacer(1, 0.3*inch))

    # Client Info
    if shipment.client or shipment.client_email:
        story.append(Paragraph("<b>Client Information</b>", styles['Heading3']))
        client_data = [
            ['Client:', shipment.client or '—'],
            ['Email:', shipment.client_email or '—'],
        ]
        client_table = Table(client_data, colWidths=[2*inch, 4*inch])
        client_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f4ff')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#0a0f1e')),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d8f0')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(client_table)
        story.append(Spacer(1, 0.3*inch))

    # Containers (if any)
    if hasattr(shipment, 'containers') and shipment.containers:
        story.append(Paragraph("<b>Containers</b>", styles['Heading3']))
        cont_data = [['Container No.', 'Seal No.', 'Type', 'Weight']]
        for c in shipment.containers:
            cont_data.append([
                c.container_no or '—',
                c.seal_no or '—',
                c.size_type or '—',
                c.weight or '—'
            ])
        cont_table = Table(cont_data, colWidths=[2*inch, 1.5*inch, 1*inch, 1.5*inch])
        cont_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a0f1e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d8f0')),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]))
        story.append(cont_table)
        story.append(Spacer(1, 0.3*inch))

    # Events timeline
    if shipment.events:
        story.append(Paragraph("<b>Timeline</b>", styles['Heading3']))
        evt_data = [['Date', 'Location', 'Description', 'Status']]
        for e in sorted(shipment.events, key=lambda x: x.timestamp, reverse=True):
            evt_data.append([
                e.timestamp[:16] if e.timestamp else '—',
                e.location or '—',
                (e.description or '—')[:40],
                e.status or '—'
            ])
        evt_table = Table(evt_data, colWidths=[1.5*inch, 1.5*inch, 2.5*inch, 1*inch])
        evt_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a0f1e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d8f0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))
        story.append(evt_table)

    # Footer
    story.append(Spacer(1, 0.5*inch))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#8892b0'),
        alignment=TA_CENTER
    )
    story.append(Paragraph(f"Generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", footer_style))
    story.append(Paragraph("FreightTrack Pro — Professional Freight Management", footer_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def generate_dashboard_pdf(stats, shipments):
    """Generate dashboard summary PDF with KPIs and shipment list."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.75*inch, bottomMargin=0.75*inch)
    styles = getSampleStyleSheet()
    story = []

    # Header
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=24, 
                                  textColor=colors.HexColor('#0a0f1e'), spaceAfter=20, alignment=TA_CENTER)
    story.append(Paragraph("FreightTrack Pro", title_style))
    story.append(Paragraph("Dashboard Report", styles['Heading2']))
    story.append(Spacer(1, 0.2*inch))

    # KPI Summary
    story.append(Paragraph("<b>Key Performance Indicators</b>", styles['Heading3']))
    kpi_data = [
        ['Total Shipments', 'In Transit', 'Delivered', 'Delayed'],
        [
            str(stats.get('total', 0)),
            str(stats.get('by_status', {}).get('Sailing', 0) + stats.get('by_status', {}).get('Transit', 0)),
            str(stats.get('by_status', {}).get('Delivered', 0)),
            str(stats.get('delayed_count', 0))
        ]
    ]
    kpi_table = Table(kpi_data, colWidths=[1.5*inch]*4)
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a0f1e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('FONTSIZE', (0, 1), (-1, -1), 16),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 1), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#d0d8f0')),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 0.3*inch))

    # Recent Shipments
    story.append(Paragraph("<b>Recent Shipments</b>", styles['Heading3']))
    ship_data = [['Reference', 'Client', 'POL → POD', 'ETA', 'Status']]
    for s in shipments[:15]:  # Top 15
        ship_data.append([
            s.ref[:15] if s.ref else '—',
            (s.client or '—')[:15],
            f"{(s.pol or '—')[:8]} → {(s.pod or '—')[:8]}",
            (s.eta or '—')[:10],
            s.status or '—'
        ])

    ship_table = Table(ship_data, colWidths=[1.3*inch, 1.3*inch, 1.8*inch, 1*inch, 1*inch])
    ship_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a0f1e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d8f0')),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    story.append(ship_table)

    # Footer
    story.append(Spacer(1, 0.5*inch))
    footer = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=9, 
                           textColor=colors.HexColor('#8892b0'), alignment=TA_CENTER)
    story.append(Paragraph(f"Generated on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", footer))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
