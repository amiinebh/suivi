import io, openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

def export_shipments_xlsx(ships):
    wb=openpyxl.Workbook(); ws=wb.active; ws.title="Shipments"
    headers=["Ref","Container/AWB","Booking No","Mode","Direction","Carrier","Vessel",
             "Client","Client Email","Shipper","Consignee","Incoterm","Agent",
             "POL","POD","ETD","ETA","Status","Stuffing Date","Quotation No","Notes"]
    ws.append(headers)
    teal=PatternFill("solid",fgColor="21808D")
    for cell in ws[1]:
        cell.font=Font(bold=True,color="FFFFFF"); cell.fill=teal
        cell.alignment=Alignment(horizontal="center")
    for s in ships:
        ws.append([s.ref, s.ref2, s.booking_no, s.mode,
                   getattr(s,"direction",None), s.carrier, getattr(s,"vessel",None),
                   s.client, s.client_email,
                   getattr(s,"shipper",None), getattr(s,"consignee",None),
                   getattr(s,"incoterm",None), getattr(s,"agent",None),
                   s.pol, s.pod, s.etd, s.eta, s.status,
                   getattr(s,"stuffing_date",None), s.quotation_number, s.note])
    for col in ws.columns:
        ml=max((len(str(c.value or "")) for c in col),default=8)
        ws.column_dimensions[col[0].column_letter].width=min(ml+4,40)
    out=io.BytesIO(); wb.save(out); return out.getvalue()
