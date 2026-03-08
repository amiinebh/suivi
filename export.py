import io
import openpyxl

def export_shipments_xlsx(ships):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Shipments"
    headers = ["Ref", "Container/AWB", "Booking No", "Mode", "Direction", "Carrier", "Vessel", "Client", "Client Email", "Shipper", "Consignee", "Incoterm", "Agent", "POL", "POD", "ETD", "ETA", "Status", "Stuffing Date", "Notes"]
    ws.append(headers)
    for s in ships:
        ws.append([
            getattr(s, 'ref', ''), getattr(s, 'ref2', ''), getattr(s, 'booking_no', ''), getattr(s, 'mode', ''),
            getattr(s, 'direction', ''), getattr(s, 'carrier', ''), getattr(s, 'vessel', ''), getattr(s, 'client', ''),
            getattr(s, 'client_email', ''), getattr(s, 'shipper', ''), getattr(s, 'consignee', ''), getattr(s, 'incoterm', ''),
            getattr(s, 'agent', ''), getattr(s, 'pol', ''), getattr(s, 'pod', ''), getattr(s, 'etd', ''),
            getattr(s, 'eta', ''), getattr(s, 'status', ''), getattr(s, 'stuffing_date', ''), getattr(s, 'notes', '') or getattr(s, 'note', '')
        ])
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.getvalue()
