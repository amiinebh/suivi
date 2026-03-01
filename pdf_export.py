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

# TEU values per container type
_TEU = {'20DRY': 1, '40HC': 2, '40DRY': 2, '40RF': 2, 'FLEXI': 2, 'TRUCK': 0}

def _calc_teu(containers):
    """Sum TEU for a list of Container ORM objects."""
    return sum(_TEU.get(c.size_type or '', 0) for c in (containers or []))


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


def generate_kpi_report_pdf(stats, shipments):
    """Generate comprehensive KPI analytics report with charts and insights."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch,
                           leftMargin=0.75*inch, rightMargin=0.75*inch)
    styles = getSampleStyleSheet()
    story = []

    # Custom styles
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], 
                                  fontSize=26, textColor=colors.HexColor('#0a0f1e'), 
                                  spaceAfter=8, alignment=TA_CENTER, fontName='Helvetica-Bold')
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], 
                                    fontSize=11, textColor=colors.HexColor('#64748b'), 
                                    spaceAfter=20, alignment=TA_CENTER)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'],
                                   fontSize=16, textColor=colors.HexColor('#0a0f1e'),
                                   spaceAfter=12, spaceBefore=16, fontName='Helvetica-Bold')

    # Header
    story.append(Paragraph("📊 FreightTrack Pro", title_style))
    story.append(Paragraph(f"KPI Analytics Report · {datetime.utcnow().strftime('%B %d, %Y')}", subtitle_style))
    story.append(Spacer(1, 0.1*inch))

    # Executive Summary Box
    exec_data = [
        ['EXECUTIVE SUMMARY'],
        [f"Total Active Shipments: {stats.get('total', 0)} | On-Time Rate: {_calc_ontime_rate(stats)}% | Average Transit: {_calc_avg_transit(shipments)} days"]
    ]
    exec_table = Table(exec_data, colWidths=[6.5*inch])
    exec_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#0a0f1e')),
        ('TEXTCOLOR', (0, 0), (0, 0), colors.white),
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (0, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 1), (0, 1), colors.HexColor('#f1f5f9')),
        ('FONTSIZE', (0, 1), (0, 1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#0a0f1e')),
    ]))
    story.append(exec_table)
    story.append(Spacer(1, 0.25*inch))

    # 1. Operational KPIs
    story.append(Paragraph("1. Operational Performance Metrics", heading_style))

    by_status = stats.get('by_status', {})
    ops_data = [
        ['Metric', 'Current', 'Target', 'Status'],
        ['Total Shipments', str(stats.get('total', 0)), '—', '✓'],
        ['In Transit', str(by_status.get('Sailing', 0) + by_status.get('Transit', 0)), '—', '✓'],
        ['Delivered', str(by_status.get('Delivered', 0)), '—', '✓'],
        ['Delayed', str(stats.get('delayed_count', 0)), '< 5%', '⚠️' if stats.get('delayed_count', 0) > stats.get('total', 1) * 0.05 else '✓'],
        ['Pending', str(by_status.get('Pending', 0)), '—', '✓'],
    ]
    ops_table = Table(ops_data, colWidths=[2.5*inch, 1.3*inch, 1.3*inch, 1.4*inch])
    ops_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(ops_table)
    story.append(Spacer(1, 0.2*inch))

    # 1b. TEU Summary
    story.append(Paragraph("1b. TEU Summary by Shipment", heading_style))
    total_teu = sum(_calc_teu(s.containers) for s in shipments)
    teu_by_mode = {}
    for s in shipments:
        mode = s.mode or 'Other'
        teu_by_mode[mode] = teu_by_mode.get(mode, 0) + _calc_teu(s.containers)

    teu_data = [['Mode', 'Shipments', 'Total TEU', 'Avg TEU/Shipment']]
    for mode, teu in teu_by_mode.items():
        count = len([s for s in shipments if (s.mode or 'Other') == mode])
        avg = round(teu / count, 1) if count else 0
        teu_data.append([mode, str(count), str(teu), str(avg)])
    teu_data.append(['ALL MODES', str(len(shipments)), str(total_teu), 
                     str(round(total_teu/len(shipments),1)) if shipments else '0'])

    teu_table = Table(teu_data, colWidths=[1.8*inch, 1.5*inch, 1.5*inch, 1.7*inch])
    teu_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e2e8f0')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(teu_table)
    story.append(Spacer(1, 0.2*inch))

    # 2. Mode Distribution

    story.append(Paragraph("2. Shipment Mode Distribution", heading_style))
    by_mode = stats.get('by_mode', {})
    mode_data = [['Mode', 'Count', 'Percentage']]
    total = stats.get('total', 1)
    for mode, count in by_mode.items():
        pct = round((count / total * 100), 1) if total > 0 else 0
        mode_data.append([mode, str(count), f"{pct}%"])

    mode_table = Table(mode_data, colWidths=[2.2*inch, 2.2*inch, 2.1*inch])
    mode_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(mode_table)
    story.append(Spacer(1, 0.2*inch))

    # 3. Top Clients
    story.append(Paragraph("3. Top Clients by Shipment Volume", heading_style))
    client_counts = {}
    for s in shipments:
        if s.client:
            client_counts[s.client] = client_counts.get(s.client, 0) + 1

    top_clients = sorted(client_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    client_data = [['Rank', 'Client', 'Shipments', 'Share']]
    for i, (client, count) in enumerate(top_clients, 1):
        share = round((count / total * 100), 1) if total > 0 else 0
        client_data.append([str(i), client[:30], str(count), f"{share}%"])

    client_table = Table(client_data, colWidths=[0.6*inch, 3*inch, 1.5*inch, 1.4*inch])
    client_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(client_table)
    story.append(Spacer(1, 0.2*inch))

    # 4. Route Analysis
    story.append(Paragraph("4. Top Trade Routes", heading_style))
    routes = {}
    for s in shipments:
        if s.pol and s.pod:
            route = f"{s.pol} → {s.pod}"
            routes[route] = routes.get(route, 0) + 1

    top_routes = sorted(routes.items(), key=lambda x: x[1], reverse=True)[:8]
    route_data = [['Rank', 'Route', 'Shipments']]
    for i, (route, count) in enumerate(top_routes, 1):
        route_data.append([str(i), route[:35], str(count)])

    route_table = Table(route_data, colWidths=[0.7*inch, 4*inch, 1.8*inch])
    route_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.75, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(route_table)

    # Footer
    story.append(Spacer(1, 0.3*inch))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], 
                                  fontSize=8, textColor=colors.HexColor('#94a3b8'), 
                                  alignment=TA_CENTER)
    story.append(Paragraph(f"Report generated on {datetime.utcnow().strftime('%Y-%m-%d at %H:%M UTC')} | FreightTrack Pro v4", footer_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()

def _calc_ontime_rate(stats):
    """Calculate on-time delivery rate."""
    delivered = stats.get('by_status', {}).get('Delivered', 0)
    delayed = stats.get('delayed_count', 0)
    total_completed = delivered + delayed
    if total_completed == 0:
        return 100
    return round((delivered / total_completed * 100), 1)

def _calc_avg_transit(shipments):
    """Calculate average transit time in days."""
    transit_days = []
    for s in shipments:
        if s.etd and s.eta:
            try:
                from datetime import datetime
                etd = datetime.fromisoformat(s.etd.replace('Z', '+00:00'))
                eta = datetime.fromisoformat(s.eta.replace('Z', '+00:00'))
                days = (eta - etd).days
                if 0 < days < 365:  # sanity check
                    transit_days.append(days)
            except:
                pass
    return round(sum(transit_days) / len(transit_days), 1) if transit_days else 0

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
    ship_data = [['Reference', 'Client', 'POL → POD', 'ETA', 'Status', 'TEU']]
    for s in shipments[:15]:  # Top 15
        ship_data.append([
            s.ref[:15] if s.ref else '—',
            (s.client or '—')[:15],
            f"{(s.pol or '—')[:8]} → {(s.pod or '—')[:8]}",
            (s.eta or '—')[:10],
            s.status or '—',
            str(_calc_teu(s.containers))
        ])

    ship_table = Table(ship_data, colWidths=[1.2*inch, 1.2*inch, 1.6*inch, 0.9*inch, 0.9*inch, 0.6*inch])
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
