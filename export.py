import io
import openpyxl

def export_shipments_xlsx(ships):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Shipments"

    headers = ["Ref", "Container/AWB", "Booking No", "Mode", "Carrier", "Client", "Client Email", "POL", "POD", "ETD", "ETA", "Status", "Notes"]
    ws.append(headers)

    for s in ships:
        ws.append([
            s.ref, s.ref2, s.bookingno, s.mode, s.carrier, s.client, s.clientemail,
            s.pol, s.pod, s.etd, s.eta, s.status, s.note
        ])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
