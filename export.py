from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from io import BytesIO
from datetime import datetime

STATUS_COLORS = {
    "In Transit": "DBEAFE", "Delivered": "DCFCE7",
    "Delayed": "FEE2E2", "Customs": "EDE9FE",
    "Pending": "FEF9C3",
}

def export_shipments_xlsx(shipments: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Shipments"

    headers = ["Reference","Container/AWB","Booking No","Mode","Carrier",
               "Vessel","POL","POD","ETD","ETA","Status","Client",
               "Client Email","Last Tracked","Created At","Notes"]

    # Header row style
    hdr_fill = PatternFill("solid", fgColor="1A365D")
    hdr_font = Font(color="FFFFFF", bold=True, size=11)
    thin = Side(style="thin", color="E2E8F0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    ws.row_dimensions[1].height = 28

    for row_i, s in enumerate(shipments, 2):
        row = [
            s.ref, s.ref2 or "", s.booking_no or "",
            s.mode, s.carrier or "", s.vessel or "",
            s.pol or "", s.pod or "",
            s.etd or "", s.eta or "", s.status,
            s.client or "", s.client_email or "",
            (s.last_tracked or "")[:19].replace("T"," "),
            (s.created_at or "")[:19].replace("T"," "),
            s.note or ""
        ]
        status_color = STATUS_COLORS.get(s.status, "F8FAFC")
        for col, val in enumerate(row, 1):
            cell = ws.cell(row=row_i, column=col, value=val)
            cell.border = border
            cell.alignment = Alignment(vertical="center")
            if col == 11:  # Status column
                cell.fill = PatternFill("solid", fgColor=status_color)
                cell.font = Font(bold=True)

    # Column widths
    widths = [14,18,14,8,16,18,14,14,12,12,13,16,22,18,18,28]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Freeze header
    ws.freeze_panes = "A2"

    # Stats sheet
    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "FreightTrack Export"
    ws2["A1"].font = Font(bold=True, size=14, color="1A365D")
    ws2["A2"] = f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    ws2["A2"].font = Font(color="718096")
    ws2["A4"] = "Total Shipments"
    ws2["B4"] = len(shipments)
    from collections import Counter
    by_status = Counter(s.status for s in shipments)
    by_mode   = Counter(s.mode for s in shipments)
    for i, (k, v) in enumerate(by_status.items(), 5):
        ws2[f"A{i}"] = k; ws2[f"B{i}"] = v
    ws2["A12"] = "By Mode"
    ws2["A12"].font = Font(bold=True)
    for i, (k, v) in enumerate(by_mode.items(), 13):
        ws2[f"A{i}"] = k; ws2[f"B{i}"] = v
    ws2.column_dimensions["A"].width = 20
    ws2.column_dimensions["B"].width = 10

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
