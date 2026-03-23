import io
import openpyxl

def export_shipments_xlsx(ships):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Shipments"

    headers = [
        "Ref", "Container/AWB", "Booking No", "Mode", "Carrier",
        "Shipper", "Consignee", "Incoterm", "Client", "Client Email",
        "POL", "POD", "ETD", "ETA", "Vessel", "Voyage",
        "Status", "TEU", "Notes"
    ]
    ws.append(headers)

    for s in ships:
        ws.append([
            getattr(s, 'ref', '') or '',
            getattr(s, 'ref2', '') or '',
            getattr(s, 'booking_no', '') or '',
            getattr(s, 'mode', '') or '',
            getattr(s, 'carrier', '') or '',
            getattr(s, 'shipper', '') or '',
            getattr(s, 'consignee', '') or '',
            getattr(s, 'incoterm', '') or '',
            getattr(s, 'client', '') or '',
            getattr(s, 'client_email', '') or '',
            getattr(s, 'pol', '') or '',
            getattr(s, 'pod', '') or '',
            str(getattr(s, 'etd', '') or ''),
            str(getattr(s, 'eta', '') or ''),
            getattr(s, 'vessel', '') or '',
            getattr(s, 'voyage', '') or '',
            getattr(s, 'status', '') or '',
            getattr(s, 'teu', '') or '',
            getattr(s, 'note', '') or '',
        ])

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()
