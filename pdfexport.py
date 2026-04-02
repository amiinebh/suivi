import io
import re
from collections import defaultdict
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
)
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics import renderPDF

# ── Colours ──────────────────────────────────────────────────────────────────
C_PRIMARY   = colors.HexColor("#1e3a5f")
C_ACCENT    = colors.HexColor("#2563eb")
C_EXPORT    = colors.HexColor("#16a34a")
C_IMPORT    = colors.HexColor("#2563eb")
C_WARN      = colors.HexColor("#dc2626")
C_ORANGE    = colors.HexColor("#ea580c")
C_LIGHT_BG  = colors.HexColor("#f1f5f9")
C_BORDER    = colors.HexColor("#cbd5e1")
C_TEXT      = colors.HexColor("#1e293b")
C_MUTED     = colors.HexColor("#64748b")
C_WHITE     = colors.white

# ── Helpers ───────────────────────────────────────────────────────────────────
def norm(v):
    """Normalise port / location name to title-case for grouping key."""
    return (v or "").strip().upper()

def norm_client(v):
    s = (v or "").strip()
    if not s or s.upper() == "UNKNOWN":
        return None
    return s.title()

def norm_carrier(v):
    s = (v or "").strip()
    if not s or s.upper() == "UNKNOWN":
        return None
    return s

def fmt_month(key):
    """2026-03 → Mar 26"""
    try:
        dt = datetime.strptime(key[:7], "%Y-%m")
        return dt.strftime("%b %y")
    except Exception:
        return key

REF_IMPORT_RE = re.compile(r"^RO(\d{2})(\d{2})(\d{3,})$", re.I)
REF_EXPORT_RE = re.compile(r"^ROE(\d{2})(\d{2})(\d{2,})$", re.I)

def ref_direction(ref):
    ref = (ref or "").strip().upper()
    if REF_EXPORT_RE.match(ref):
        return "Export"
    if REF_IMPORT_RE.match(ref):
        return "Import"
    return None

def ship_direction(s):
    d = (getattr(s, "direction", None) or "").strip().lower()
    if d in ("export", "exp", "x"):
        return "Export"
    if d in ("import", "imp", "m"):
        return "Import"
    rd = ref_direction(getattr(s, "ref", None))
    return rd or "Import"

def safe_num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


# ── Styles ────────────────────────────────────────────────────────────────────
def _styles():
    ss = getSampleStyleSheet()
    def add(name, **kw):
        ss.add(ParagraphStyle(name=name, **kw))
    add("FT_Title",    fontName="Helvetica-Bold",  fontSize=20, textColor=C_PRIMARY,  spaceAfter=2)
    add("FT_Sub",      fontName="Helvetica",        fontSize=9,  textColor=C_MUTED,    spaceAfter=6)
    add("FT_Section",  fontName="Helvetica-Bold",   fontSize=11, textColor=C_PRIMARY,  spaceBefore=10, spaceAfter=4)
    add("FT_Label",    fontName="Helvetica",         fontSize=8,  textColor=C_MUTED)
    add("FT_Value",    fontName="Helvetica-Bold",    fontSize=8,  textColor=C_TEXT)
    add("FT_Small",    fontName="Helvetica",         fontSize=7,  textColor=C_MUTED)
    add("FT_Tag_Exp",  fontName="Helvetica-Bold",    fontSize=7,  textColor=C_EXPORT)
    add("FT_Tag_Imp",  fontName="Helvetica-Bold",    fontSize=7,  textColor=C_IMPORT)
    return ss

SS = _styles()


# ── KPI Summary bar ───────────────────────────────────────────────────────────
def _kpi_table(total, exp_c, imp_c, teu, overdue):
    medals = [
        ("#SHIPMENTS", str(total),   C_TEXT,   C_ACCENT),
        ("↑ EXPORT",   str(exp_c),   C_EXPORT, colors.HexColor("#dcfce7")),
        ("↓ IMPORT",   str(imp_c),   C_IMPORT, colors.HexColor("#dbeafe")),
        ("TEU",        str(int(teu) if teu == int(teu) else round(teu,1)), C_TEXT, C_LIGHT_BG),
        ("OVERDUE",    str(overdue), C_WARN if overdue else C_MUTED, colors.HexColor("#fee2e2") if overdue else C_LIGHT_BG),
    ]
    cells = []
    for label, val, vc, bg in medals:
        cells.append(
            Table(
                [[Paragraph(f'<font size="18"><b>{val}</b></font>', ParagraphStyle("v", textColor=vc, fontSize=18, fontName="Helvetica-Bold"))],
                 [Paragraph(label, ParagraphStyle("l", textColor=C_MUTED, fontSize=7, fontName="Helvetica-Bold"))]],
                colWidths=[3*cm],
                style=[
                    ("ALIGN", (0,0), (-1,-1), "CENTER"),
                    ("BACKGROUND", (0,0), (-1,-1), bg),
                    ("ROUNDEDCORNERS", [6]),
                    ("BOX", (0,0), (-1,-1), 0.5, C_BORDER),
                    ("TOPPADDING", (0,0), (-1,-1), 6),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ]
            )
        )
    row = Table([cells], colWidths=[3.2*cm]*5)
    row.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",  (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))
    return row


# ── Monthly bar chart ─────────────────────────────────────────────────────────
def _monthly_chart(monthly):
    if not monthly:
        return Paragraph("No monthly data yet.", SS["FT_Small"])
    labels = [fmt_month(m["month"]) for m in monthly]
    values = [m["count"] for m in monthly]
    imp_v  = [m.get("import_count", 0) for m in monthly]
    exp_v  = [m.get("export_count", 0) for m in monthly]

    W, H = 16*cm, 6*cm
    d = Drawing(W, H)

    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 1*cm, 0.8*cm, W - 1.5*cm, H - 1.2*cm
    bc.data = [imp_v, exp_v]
    bc.groupSpacing = 4
    bc.barSpacing = 1
    bc.bars[0].fillColor = C_IMPORT
    bc.bars[1].fillColor = C_EXPORT
    bc.valueAxis.visibleGrid = True
    bc.valueAxis.gridStrokeColor = colors.HexColor("#e2e8f0")
    bc.valueAxis.gridStrokeWidth = 0.5
    bc.valueAxis.labelTextFormat = "%d"
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fillColor = C_MUTED
    bc.categoryAxis.categoryNames = labels
    bc.categoryAxis.labels.fontSize = 7
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fillColor = C_MUTED
    bc.categoryAxis.labels.angle = 0
    bc.categoryAxis.labels.dy = -4
    bc.categoryAxis.strokeWidth = 0
    bc.valueAxis.strokeWidth = 0
    bc.strokeWidth = 0
    d.add(bc)

    # Legend
    leg_x = 2*cm
    for i, (lbl, col) in enumerate([("Import (RO)", C_IMPORT), ("Export (ROE)", C_EXPORT)]):
        rx = leg_x + i * 5.5*cm
        d.add(Rect(rx, H - 0.55*cm, 0.35*cm, 0.22*cm, fillColor=col, strokeWidth=0))
        d.add(String(rx + 0.45*cm, H - 0.52*cm, lbl, fontSize=7, fontName="Helvetica", fillColor=C_MUTED))
    return d


# ── Rank table ─────────────────────────────────────────────────────────────────
MEDALS = ["🥇", "🥈", "🥉"] + [str(i) for i in range(4, 20)]

def _rank_table(items, name_key="name", count_key="count", teu_key=None, col_label="Ships", total=None):
    if not items:
        return Paragraph("No data.", SS["FT_Small"])
    if total is None:
        total = sum(it.get(count_key, 0) for it in items) or 1
    headers = ["#", "Name", col_label, "%"]
    if teu_key:
        headers = ["#", "Name", col_label, "TEU", "%"]
    col_w = [0.55*cm, 5.5*cm, 1.4*cm, 1.2*cm] if not teu_key else [0.55*cm, 4.8*cm, 1.2*cm, 1.2*cm, 1.0*cm]
    rows = [headers]
    for i, it in enumerate(items[:8]):
        cnt = it.get(count_key, 0)
        pct = f'{round(cnt/total*100)}%'
        row = [MEDALS[i] if i < 3 else str(i+1), it.get(name_key, ""), str(cnt), pct]
        if teu_key:
            row = [MEDALS[i] if i < 3 else str(i+1), it.get(name_key, ""), str(cnt),
                   str(int(it.get(teu_key, 0))), pct]
        rows.append(row)
    t = Table(rows, colWidths=col_w)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  C_PRIMARY),
        ("TEXTCOLOR",     (0,0), (-1,0),  C_WHITE),
        ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 7),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("TEXTCOLOR",     (0,1), (-1,-1), C_TEXT),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_LIGHT_BG]),
        ("ALIGN",         (2,0), (-1,-1), "RIGHT"),
        ("ALIGN",         (0,0), (0,-1),  "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("BOX",           (0,0), (-1,-1), 0.5, C_BORDER),
        ("LINEBELOW",     (0,0), (-1,0),  0.5, C_BORDER),
    ]))
    return t


def _section_header(title, icon=""):
    return Paragraph(f'{icon} {title}', SS["FT_Section"])


def _dir_badge(direction):
    col = C_EXPORT if direction == "Export" else C_IMPORT
    arrow = "↑" if direction == "Export" else "↓"
    return Paragraph(f'<font color="#{col.hexval()[1:]}"><b>{arrow} {direction}</b></font>', SS["FT_Value"])


# ── Recent shipments table ─────────────────────────────────────────────────────
def _recent_table(ships, direction, limit=10):
    filtered = [s for s in ships if ship_direction(s) == direction]
    active = [s for s in filtered if (getattr(s, "status", "") or "") not in ("Closed", "Canceled")]
    subset = (active + [s for s in filtered if s not in active])[:limit]
    if not subset:
        return Paragraph(f'No {direction.lower()} shipments.', SS["FT_Small"])
    headers = ["Ref", "Client", "POL → POD", "ETA", "Status"]
    cw = [2.5*cm, 3.5*cm, 4*cm, 2*cm, 2.5*cm]
    rows = [headers]
    for s in subset:
        pol = norm(getattr(s, "pol", "") or "")
        pod = norm(getattr(s, "pod", "") or "")
        eta = str(getattr(s, "eta", "") or "")[:10]
        status = getattr(s, "status", "") or ""
        rows.append([
            getattr(s, "ref", "") or "",
            (getattr(s, "client", "") or "—"),
            f'{pol} → {pod}' if pol or pod else "—",
            eta or "—",
            status,
        ])
    t = Table(rows, colWidths=cw)
    bg = colors.HexColor("#dcfce7") if direction == "Export" else colors.HexColor("#dbeafe")
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_PRIMARY if direction == "Export" else C_ACCENT),
        ("TEXTCOLOR",     (0,0), (-1,0), C_WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 7),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("TEXTCOLOR",     (0,1), (-1,-1), C_TEXT),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, bg]),
        ("ALIGN",         (0,0), (-1,-1), "LEFT"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("BOX",           (0,0), (-1,-1), 0.5, C_BORDER),
    ]))
    return t


# ── Overdue table ──────────────────────────────────────────────────────────────
def _overdue_table(ships):
    today = datetime.utcnow().date()
    overdue = []
    for s in ships:
        eta_raw = getattr(s, "eta", None)
        if not eta_raw:
            continue
        try:
            eta = datetime.fromisoformat(str(eta_raw).replace("Z", "+00:00")).date()
        except Exception:
            continue
        status = (getattr(s, "status", "") or "").strip()
        if status in ("Closed", "Arrived", "Canceled"):
            continue
        if eta < today:
            overdue.append((s, (today - eta).days))
    overdue.sort(key=lambda x: -x[1])
    if not overdue:
        return Paragraph("✓ No overdue shipments", ParagraphStyle("ok", textColor=C_EXPORT, fontSize=9, fontName="Helvetica-Bold"))
    headers = ["Ref", "Client", "ETA", "Days Late", "Status"]
    cw = [2.5*cm, 3.5*cm, 2.5*cm, 2*cm, 2.5*cm]
    rows = [headers]
    for s, days in overdue[:10]:
        rows.append([
            getattr(s, "ref", "") or "",
            (getattr(s, "client", "") or "—"),
            str(getattr(s, "eta", "") or "")[:10],
            str(days) + "d",
            getattr(s, "status", "") or "",
        ])
    t = Table(rows, colWidths=cw)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), C_WARN),
        ("TEXTCOLOR",     (0,0), (-1,0), C_WHITE),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,-1), 7),
        ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
        ("TEXTCOLOR",     (0,1), (-1,-1), C_TEXT),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, colors.HexColor("#fee2e2")]),
        ("ALIGN",         (3,0), (3,-1), "RIGHT"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("BOX",           (0,0), (-1,-1), 0.5, C_BORDER),
    ]))
    return t


# ── Two-col layout helper ──────────────────────────────────────────────────────
def _two_col(left, right, lw=8.2*cm, rw=8.2*cm, gap=0.6*cm):
    t = Table([[left, right]], colWidths=[lw, rw])
    t.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
    ]))
    return t


# ── Page header/footer ─────────────────────────────────────────────────────────
def _on_page(canvas, doc):
    W, H = A4
    canvas.saveState()
    # Header stripe
    canvas.setFillColor(C_PRIMARY)
    canvas.rect(0, H - 1.6*cm, W, 1.6*cm, fill=True, stroke=False)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.setFillColor(C_WHITE)
    canvas.drawString(1.5*cm, H - 1.1*cm, "FreightTrack Pro  —  Operations Report")
    # Footer
    canvas.setFillColor(C_MUTED)
    canvas.setFont("Helvetica", 7)
    ts = datetime.now().strftime("Generated %d %b %Y at %H:%M")
    canvas.drawString(1.5*cm, 0.7*cm, ts)
    canvas.drawRightString(W - 1.5*cm, 0.7*cm, f'Page {doc.page}')
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(1.5*cm, 0.9*cm, W - 1.5*cm, 0.9*cm)
    canvas.restoreState()


# ── Main: generate_dashboard_pdf ───────────────────────────────────────────────
def generate_dashboard_pdf(stats, shipments):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2.2*cm, bottomMargin=1.8*cm,
        title="FreightTrack Pro — Operations Report",
    )

    ships = list(shipments)
    today = datetime.utcnow().date()

    # ── Aggregate ────────────────────────────────────────────────────────────
    total = len(ships)
    total_teu = sum(safe_num(getattr(s, "teu", 0)) for s in ships)
    by_status = defaultdict(int)
    by_mode   = defaultdict(int)
    by_dir    = defaultdict(int)
    carrier_map = defaultdict(lambda: {"all": 0, "Export": 0, "Import": 0})
    client_map  = defaultdict(lambda: {"ships": 0, "teu": 0.0, "Export": 0, "Import": 0,
                                        "teu_exp": 0.0, "teu_imp": 0.0})
    pol_map = defaultdict(lambda: {"all": 0, "Export": 0, "Import": 0})
    pod_map = defaultdict(lambda: {"all": 0, "Export": 0, "Import": 0})
    route_map = defaultdict(lambda: {"all": 0, "Export": 0, "Import": 0})
    month_imp = defaultdict(int)
    month_exp = defaultdict(int)

    overdue_count = 0
    for s in ships:
        st  = (getattr(s, "status", "") or "Pending").strip()
        md  = (getattr(s, "mode", "Ocean") or "Ocean").strip()
        dr  = ship_direction(s)
        teu = safe_num(getattr(s, "teu", 0))
        cl  = norm_client(getattr(s, "client", None))
        ca  = norm_carrier(getattr(s, "carrier", None))
        pol = norm(getattr(s, "pol", None) or "")
        pod = norm(getattr(s, "pod", None) or "")
        ref = getattr(s, "ref", "") or ""
        eta_raw = getattr(s, "eta", None)

        by_status[st]  += 1
        by_mode[md]    += 1
        by_dir[dr]     += 1

        # monthly via ref
        import re as _re
        m_imp = _re.match(r"^RO(\d{2})(\d{2})(\d{3,})$", ref.upper())
        m_exp = _re.match(r"^ROE(\d{2})(\d{2})(\d{2,})$", ref.upper())
        if m_imp:
            yy, mm, seq = m_imp.groups()
            k = f"20{yy}-{mm}"
            month_imp[k] = max(month_imp[k], int(seq))
        elif m_exp:
            yy, mm, seq = m_exp.groups()
            k = f"20{yy}-{mm}"
            month_exp[k] = max(month_exp[k], int(seq))

        if cl:
            client_map[cl]["ships"] += 1
            client_map[cl]["teu"]   += teu
            client_map[cl][dr]      += 1
            if dr == "Export": client_map[cl]["teu_exp"] += teu
            else:               client_map[cl]["teu_imp"] += teu

        if ca:
            carrier_map[ca]["all"] += 1
            carrier_map[ca][dr]    += 1

        if pol:
            pol_map[pol]["all"] += 1
            pol_map[pol][dr]    += 1
        if pod:
            pod_map[pod]["all"] += 1
            pod_map[pod][dr]    += 1
        if pol and pod:
            rk = f"{pol} to {pod}"
            route_map[rk]["all"] += 1
            route_map[rk][dr]    += 1

        if eta_raw and st not in ("Closed", "Arrived", "Canceled"):
            try:
                eta_d = datetime.fromisoformat(str(eta_raw).replace("Z","+00:00")).date()
                if eta_d < today:
                    overdue_count += 1
            except Exception:
                pass

    exp_c = by_dir.get("Export", 0)
    imp_c = by_dir.get("Import", 0)

    monthly = []
    for mk in sorted(set(month_imp) | set(month_exp)):
        monthly.append({
            "month": mk,
            "count": month_imp.get(mk, 0) + month_exp.get(mk, 0),
            "import_count": month_imp.get(mk, 0),
            "export_count": month_exp.get(mk, 0),
        })

    def top(d, sub_key, n=8):
        rows = [{"name": k, "count": v[sub_key]} for k, v in d.items() if v[sub_key] > 0]
        return sorted(rows, key=lambda x: -x["count"])[:n]

    def top_clients(dr):
        rows = []
        for name, v in client_map.items():
            cnt = v[dr]
            if cnt == 0:
                continue
            rows.append({"name": name, "count": cnt,
                         "teu": round(v["teu_exp"] if dr == "Export" else v["teu_imp"], 1)})
        return sorted(rows, key=lambda x: -x["count"])[:8]

    # ── Build story ───────────────────────────────────────────────────────────
    story = []

    # KPI bar
    story.append(Spacer(1, 0.3*cm))
    story.append(_kpi_table(total, exp_c, imp_c, total_teu, overdue_count))
    story.append(Spacer(1, 0.4*cm))

    # Monthly chart
    story.append(_section_header("Monthly Shipment Volume (RO Import + ROE Export)", "📈"))
    story.append(_monthly_chart(monthly))
    story.append(Spacer(1, 0.4*cm))

    # Status + Mode + Direction
    def _mini_dist(title, data, icon=""):
        tot = sum(data.values()) or 1
        rows = [[Paragraph(f'<b>{icon} {title}</b>', SS["FT_Label"])]]
        for k, v in sorted(data.items(), key=lambda x: -x[1]):
            pct = round(v / tot * 100)
            rows.append([Paragraph(f'{k}  <b>{v}</b>  <font color="#64748b">{pct}%</font>', SS["FT_Small"])])
        t = Table(rows, colWidths=[7.5*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0), C_LIGHT_BG),
            ("BOX",           (0,0), (-1,-1), 0.5, C_BORDER),
            ("TOPPADDING",    (0,0), (-1,-1), 3),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ]))
        return t

    dist_row = Table(
        [[_mini_dist("Status", dict(by_status), "📦"),
          _mini_dist("Mode",   dict(by_mode),   "🚢"),
          _mini_dist("Direction", {"Export": exp_c, "Import": imp_c}, "↕️")]],
        colWidths=[5.5*cm, 5.5*cm, 5.5*cm]
    )
    dist_row.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    story.append(dist_row)
    story.append(Spacer(1, 0.5*cm))

    # Clients
    story.append(_section_header("Top Clients — Shipments & TEU", "👥"))
    cl_row = _two_col(
        KeepTogether([_dir_badge("Export"), Spacer(1, 2), _rank_table(top_clients("Export"), teu_key="teu", col_label="Ships")]),
        KeepTogether([_dir_badge("Import"), Spacer(1, 2), _rank_table(top_clients("Import"), teu_key="teu", col_label="Ships")]),
    )
    story.append(cl_row)
    story.append(Spacer(1, 0.4*cm))

    # Carriers
    story.append(_section_header("Top Carriers", "🚢"))
    ca_row = _two_col(
        KeepTogether([_dir_badge("Export"), Spacer(1, 2), _rank_table(top(carrier_map, "Export"))]),
        KeepTogether([_dir_badge("Import"), Spacer(1, 2), _rank_table(top(carrier_map, "Import"))]),
    )
    story.append(ca_row)
    story.append(Spacer(1, 0.4*cm))

    # POD / POL
    story.append(_section_header("Top Destinations (POD)", "📍"))
    pod_row = _two_col(
        KeepTogether([_dir_badge("Export"), Spacer(1, 2), _rank_table(top(pod_map, "Export"))]),
        KeepTogether([_dir_badge("Import"), Spacer(1, 2), _rank_table(top(pod_map, "Import"))]),
    )
    story.append(pod_row)
    story.append(Spacer(1, 0.4*cm))

    story.append(_section_header("Top Origins (POL)", "📌"))
    pol_row = _two_col(
        KeepTogether([_dir_badge("Export"), Spacer(1, 2), _rank_table(top(pol_map, "Export"))]),
        KeepTogether([_dir_badge("Import"), Spacer(1, 2), _rank_table(top(pol_map, "Import"))]),
    )
    story.append(pol_row)
    story.append(Spacer(1, 0.4*cm))

    # Routes
    story.append(_section_header("Top Routings (POL → POD)", "🔀"))
    rt_row = _two_col(
        KeepTogether([_dir_badge("Export"), Spacer(1, 2),
                      _rank_table(top(route_map, "Export"), name_key="name", count_key="count")]),
        KeepTogether([_dir_badge("Import"), Spacer(1, 2),
                      _rank_table(top(route_map, "Import"), name_key="name", count_key="count")]),
    )
    story.append(rt_row)
    story.append(Spacer(1, 0.5*cm))

    # Overdue
    story.append(_section_header("Overdue Shipments", "⚠️"))
    story.append(_overdue_table(ships))
    story.append(Spacer(1, 0.5*cm))

    # Recent
    story.append(_section_header("Recent Active Shipments", "📋"))
    rec_row = _two_col(
        KeepTogether([_dir_badge("Export"), Spacer(1, 2), _recent_table(ships, "Export")]),
        KeepTogether([_dir_badge("Import"), Spacer(1, 2), _recent_table(ships, "Import")]),
    )
    story.append(rec_row)

    # Footer note
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_BORDER))
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        f'FreightTrack Pro · Report generated {datetime.now().strftime("%d %b %Y at %H:%M")} · {total} shipments · {int(total_teu)} TEU',
        ParagraphStyle("foot", fontName="Helvetica", fontSize=7, textColor=C_MUTED, alignment=1)
    ))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()


# ── Single shipment PDF (unchanged skeleton) ───────────────────────────────────
def generate_shipment_pdf(s):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=2*cm, bottomMargin=1.5*cm)
    story = []
    def row(label, val):
        return [Paragraph(f'<b>{label}</b>', SS["FT_Label"]),
                Paragraph(str(val or "—"), SS["FT_Value"])]

    t = Table([
        row("Reference", getattr(s, "ref", "")),
        row("AWB / Container", getattr(s, "ref2", "")),
        row("Booking No.", getattr(s, "bookingno", "")),
        row("Mode", getattr(s, "mode", "")),
        row("Carrier", getattr(s, "carrier", "")),
        row("Shipper", getattr(s, "shipper", "")),
        row("Consignee", getattr(s, "consignee", "")),
        row("Client", getattr(s, "client", "")),
        row("Incoterm", getattr(s, "incoterm", "")),
        row("POL", getattr(s, "pol", "")),
        row("POD", getattr(s, "pod", "")),
        row("ETD", str(getattr(s, "etd", "") or "")[:10]),
        row("ETA", str(getattr(s, "eta", "") or "")[:10]),
        row("Vessel", getattr(s, "vessel", "")),
        row("Voyage", getattr(s, "voyage", "")),
        row("Status", getattr(s, "status", "")),
        row("TEU", getattr(s, "teu", "")),
        row("Note", getattr(s, "note", "")),
    ], colWidths=[4*cm, 13*cm])
    t.setStyle(TableStyle([
        ("FONTSIZE",      (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS",(0,0), (-1,-1), [C_WHITE, C_LIGHT_BG]),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("BOX",           (0,0), (-1,-1), 0.5, C_BORDER),
    ]))
    story.append(Paragraph(f'Shipment: {getattr(s,"ref","")}', SS["FT_Title"]))
    story.append(Spacer(1, 0.3*cm))
    story.append(t)
    doc.build(story)
    return buf.getvalue()
