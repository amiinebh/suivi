from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Quotation, QuotationCharge, QuotationContainer
from auth import get_current_user
from datetime import datetime
from io import BytesIO
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
except ImportError:
    # If reportlab not installed, PDF will return error
    pass

router = APIRouter(prefix="/api/quotations", tags=["quotations"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _s(q):
    return {
        "id": q.id, "ref": q.ref, "mode": q.mode,
        "client": q.client, "clientemail": q.client_email,
        "carrier": q.carrier, "pol": q.pol, "pod": q.pod,
        "bookingno": q.booking_no, "incoterm": q.incoterm,
        "validitydate": q.validity_date, "status": q.status, "note": q.note,
        "shipper": q.shipper, "consignee": q.consignee, "currency": q.currency,
        "createdat": q.created_at, "updatedat": q.updated_at,
        "charges": [{"id": c.id, "name": c.name, "amount": c.amount,
                     "currency": c.currency, "unit": c.unit, "note": c.note}
                    for c in (q.charges or [])],
        "containers": [{"id": ct.id, "qty": ct.qty, "ctype": ct.ctype}
                       for ct in (q.containers or [])],
    }

@router.get("")
def list_quotations(q: str = "", status: str = "", mode: str = "",
                    db: Session = Depends(get_db), current=Depends(get_current_user)):
    qs = db.query(Quotation)
    if q:
        like = f"%{q}%"
        qs = qs.filter(Quotation.ref.ilike(like) | Quotation.client.ilike(like) |
                       Quotation.pol.ilike(like)  | Quotation.pod.ilike(like))
    if status and status not in ("", "All Status"):
        qs = qs.filter(Quotation.status == status)
    if mode and mode not in ("", "All Modes"):
        qs = qs.filter(Quotation.mode == mode)
    return [_s(r) for r in qs.order_by(Quotation.id.desc()).all()]

@router.get("/{qid}")
def get_quotation(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q: raise HTTPException(404, "Quotation not found")
    return _s(q)

@router.post("")
async def create_quotation(request: Request, db: Session = Depends(get_db),
                            current=Depends(get_current_user)):
    try: body = await request.json()
    except Exception: raise HTTPException(400, "Invalid JSON body")
    ref = (body.get("ref") or "").strip()
    if not ref: raise HTTPException(400, "Quotation Ref is required")
    if db.query(Quotation).filter(Quotation.ref == ref).first():
        raise HTTPException(400, "Ref already exists")
    now = datetime.utcnow().isoformat()
    q = Quotation(ref=ref, mode=body.get("mode") or "Ocean",
                  client=body.get("client"), client_email=body.get("clientemail"),
                  carrier=body.get("carrier"), pol=body.get("pol"), pod=body.get("pod"),
                  booking_no=body.get("bookingno"), incoterm=body.get("incoterm"),
                  validity_date=body.get("validitydate"),
                  status=body.get("status") or "Pending", note=body.get("note"),
                  shipper=body.get("shipper"), consignee=body.get("consignee"),
                  currency=body.get("currency") or "USD",
                  created_at=now, updated_at=now)
    db.add(q); db.flush()
    for c in (body.get("charges") or []):
        if c.get("name"):
            db.add(QuotationCharge(quotation_id=q.id, name=c["name"],
                                   amount=c.get("amount"), currency=c.get("currency","USD"),
                                   unit=c.get("unit"), note=c.get("note")))
    for ct in (body.get("containers") or []):
        if ct.get("qty") and ct.get("ctype"):
            db.add(QuotationContainer(quotation_id=q.id, qty=int(ct["qty"]), ctype=ct["ctype"]))
    db.commit(); db.refresh(q)
    return _s(q)

@router.put("/{qid}")
@router.patch("/{qid}")
async def update_quotation(qid: int, request: Request, db: Session = Depends(get_db),
                            current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q: raise HTTPException(404, "Quotation not found")
    body = await request.json()
    fmap = {"mode":"mode","client":"client","clientemail":"client_email",
            "carrier":"carrier","pol":"pol","pod":"pod",
            "bookingno":"booking_no","incoterm":"incoterm","validitydate":"validity_date",
            "status":"status","note":"note","shipper":"shipper","consignee":"consignee",
            "currency":"currency"}
    for jk, ma in fmap.items():
        if jk in body: setattr(q, ma, body[jk] or None)
    if "charges" in body:
        db.query(QuotationCharge).filter(QuotationCharge.quotation_id == qid).delete()
        for c in (body["charges"] or []):
            if c.get("name"):
                db.add(QuotationCharge(quotation_id=qid, name=c["name"],
                                       amount=c.get("amount"), currency=c.get("currency","USD"),
                                       unit=c.get("unit"), note=c.get("note")))
    if "containers" in body:
        db.query(QuotationContainer).filter(QuotationContainer.quotation_id == qid).delete()
        for ct in (body["containers"] or []):
            if ct.get("qty") and ct.get("ctype"):
                db.add(QuotationContainer(quotation_id=qid, qty=int(ct["qty"]), ctype=ct["ctype"]))
    q.updated_at = datetime.utcnow().isoformat()
    db.commit(); db.refresh(q)
    return _s(q)

@router.delete("/{qid}")
def delete_quotation(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q: raise HTTPException(404, "Quotation not found")
    db.delete(q); db.commit()
    return {"ok": True}

@router.get("/{qid}/pdf")
def download_pdf(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    """Generate professional PDF for quotation"""
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q: raise HTTPException(404, "Quotation not found")

    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm,
                                leftMargin=15*mm, rightMargin=15*mm)
        story = []
        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                      fontSize=20, textColor=colors.HexColor('#21808D'),
                                      spaceAfter=6, alignment=TA_CENTER, fontName='Helvetica-Bold')
        heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'],
                                        fontSize=12, textColor=colors.HexColor('#21808D'),
                                        spaceAfter=6, spaceBefore=12, fontName='Helvetica-Bold')
        normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'],
                                       fontSize=9, leading=11)
        small_style = ParagraphStyle('CustomSmall', parent=styles['Normal'],
                                      fontSize=8, textColor=colors.grey)

        # Header
        story.append(Paragraph("FREIGHT QUOTATION", title_style))
        story.append(Spacer(1, 4*mm))

        # Company header (placeholder - customize with your logo/details)
        header_data = [
            [Paragraph("<b>FreightTrack Pro</b><br/>Your Logistics Partner<br/>info@freighttrack.com", small_style),
             Paragraph(f"<b>Quotation Ref:</b> {q.ref}<br/><b>Date:</b> {q.created_at[:10] if q.created_at else ''}<br/><b>Valid Until:</b> {q.validity_date or 'N/A'}", small_style)]
        ]
        header_table = Table(header_data, colWidths=[90*mm, 90*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN', (0,0), (0,0), 'LEFT'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 6*mm))

        # Client info
        story.append(Paragraph("CLIENT INFORMATION", heading_style))
        client_data = [
            ["Client:", q.client or "N/A", "Email:", q.client_email or "N/A"],
        ]
        client_table = Table(client_data, colWidths=[25*mm, 65*mm, 20*mm, 70*mm])
        client_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(client_table)
        story.append(Spacer(1, 4*mm))

        # Shipment details
        story.append(Paragraph("SHIPMENT DETAILS", heading_style))
        ship_data = [
            ["Mode:", q.mode or "N/A", "Incoterm:", q.incoterm or "N/A"],
            ["Port of Loading:", q.pol or "N/A", "Port of Discharge:", q.pod or "N/A"],
            ["Carrier:", q.carrier or "N/A", "Booking No:", q.booking_no or "N/A"],
        ]
        ship_table = Table(ship_data, colWidths=[30*mm, 60*mm, 35*mm, 55*mm])
        ship_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F5F5F5')),
            ('BACKGROUND', (2,0), (2,-1), colors.HexColor('#F5F5F5')),
        ]))
        story.append(ship_table)
        story.append(Spacer(1, 4*mm))

        # Containers
        if q.containers:
            story.append(Paragraph("CONTAINERS", heading_style))
            cont_data = [["Quantity", "Type"]]
            for ct in q.containers:
                cont_data.append([str(ct.qty), ct.ctype])
            cont_table = Table(cont_data, colWidths=[40*mm, 140*mm])
            cont_table.setStyle(TableStyle([
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#21808D')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F9F9F9')]),
            ]))
            story.append(cont_table)
            story.append(Spacer(1, 4*mm))

        # Charges
        story.append(Paragraph("CHARGES BREAKDOWN", heading_style))
        if q.charges:
            charge_data = [["Description", "Amount", "Currency", "Unit"]]
            totals = {}
            for c in q.charges:
                charge_data.append([c.name, c.amount or "0", c.currency or "USD", c.unit or ""])
                try:
                    amt = float(c.amount or 0)
                    curr = c.currency or "USD"
                    totals[curr] = totals.get(curr, 0) + amt
                except: pass

            charge_table = Table(charge_data, colWidths=[80*mm, 35*mm, 30*mm, 35*mm])
            charge_table.setStyle(TableStyle([
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('ALIGN', (1,0), (2,-1), 'RIGHT'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#21808D')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F9F9F9')]),
            ]))
            story.append(charge_table)
            story.append(Spacer(1, 3*mm))

            # Total
            total_parts = [f"{v:,.2f} {k}" for k,v in totals.items()]
            total_str = " + ".join(total_parts) if total_parts else "0.00"
            total_data = [["", "TOTAL:", total_str, ""]]
            total_table = Table(total_data, colWidths=[80*mm, 35*mm, 30*mm, 35*mm])
            total_table.setStyle(TableStyle([
                ('FONTNAME', (1,0), (2,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,-1), 10),
                ('ALIGN', (1,0), (2,0), 'RIGHT'),
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F0F0F0')),
                ('LINEABOVE', (0,0), (-1,0), 1.5, colors.HexColor('#21808D')),
            ]))
            story.append(total_table)
        else:
            story.append(Paragraph("No charges specified.", normal_style))

        story.append(Spacer(1, 6*mm))

        # Notes
        if q.note:
            story.append(Paragraph("NOTES", heading_style))
            story.append(Paragraph(q.note.replace('\n', '<br/>'), normal_style))

        # Footer
        story.append(Spacer(1, 10*mm))
        story.append(Paragraph("This quotation is valid until the date specified above. Terms and conditions apply.", small_style))

        doc.build(story)
        buffer.seek(0)

        return Response(content=buffer.getvalue(), media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=quotation_{q.ref}.pdf"})

    except Exception as e:
        raise HTTPException(500, f"PDF generation failed: {str(e)}")
