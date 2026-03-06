from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Quotation, QuotationCharge, QuotationContainer
from auth import get_current_user
from datetime import datetime
from io import BytesIO

router = APIRouter(prefix="/api/quotations", tags=["quotations"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _serialize(q):
    return {
        "id": q.id, "ref": q.ref, "mode": q.mode, "client": q.client,
        "clientemail": q.client_email, "carrier": q.carrier, "pol": q.pol, "pod": q.pod,
        "bookingno": q.booking_no, "incoterm": q.incoterm, "validitydate": q.validity_date,
        "status": q.status, "note": q.note, "currency": q.currency,
        "createdat": q.created_at, "updatedat": q.updated_at,
        "charges": [{"id": c.id, "name": c.name, "amount": c.amount, "currency": c.currency, "unit": c.unit, "note": c.note} for c in (q.charges or [])],
        "containers": [{"id": c.id, "qty": c.qty, "ctype": c.ctype} for c in (q.containers or [])],
    }

def _next_ref(db: Session):
    year = datetime.utcnow().year
    prefix = f"QUO-{year}-"
    rows = db.query(Quotation).filter(Quotation.ref.like(f"{prefix}%")).all()
    mx = 0
    for r in rows:
        try:
            mx = max(mx, int((r.ref or '').split('-')[-1]))
        except Exception:
            pass
    return f"{prefix}{str(mx+1).zfill(3)}"

@router.get('/next-ref')
def next_ref(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return {"ref": _next_ref(db)}

@router.get('')
def list_quotations(q: str = '', status: str = '', mode: str = '', db: Session = Depends(get_db), current=Depends(get_current_user)):
    qs = db.query(Quotation)
    if q:
        like = f"%{q}%"
        qs = qs.filter(Quotation.ref.ilike(like) | Quotation.client.ilike(like) | Quotation.pol.ilike(like) | Quotation.pod.ilike(like))
    if status and status not in ('', 'All Status'):
        qs = qs.filter(Quotation.status == status)
    if mode and mode not in ('', 'All Modes'):
        qs = qs.filter(Quotation.mode == mode)
    return [_serialize(x) for x in qs.order_by(Quotation.id.desc()).all()]

@router.get('/{qid}')
def get_quotation(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(404, 'Quotation not found')
    return _serialize(q)

@router.post('')
async def create_quotation(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, 'Invalid JSON body')
    ref = (body.get('ref') or '').strip() or _next_ref(db)
    if db.query(Quotation).filter(Quotation.ref == ref).first():
        ref = _next_ref(db)
    now = datetime.utcnow().isoformat()
    try:
        q = Quotation(
            ref=ref,
            mode=body.get('mode') or 'Ocean',
            client=body.get('client'),
            client_email=body.get('clientemail'),
            carrier=body.get('carrier'),
            pol=body.get('pol'),
            pod=body.get('pod'),
            booking_no=body.get('bookingno'),
            incoterm=body.get('incoterm'),
            validity_date=body.get('validitydate'),
            status=body.get('status') or 'Pending',
            note=body.get('note'),
            currency=body.get('currency') or 'USD',
            created_at=now,
            updated_at=now,
        )
        db.add(q)
        db.flush()
        for c in (body.get('charges') or []):
            if c.get('name'):
                db.add(QuotationCharge(
                    quotation_id=q.id,
                    name=str(c.get('name')),
                    amount=None if c.get('amount') in (None, '') else str(c.get('amount')),
                    currency=str(c.get('currency') or 'USD'),
                    unit=str(c.get('unit') or ''),
                    note=str(c.get('note') or ''),
                ))
        for ct in (body.get('containers') or []):
            qty = ct.get('qty')
            ctype = ct.get('ctype')
            if qty and ctype:
                db.add(QuotationContainer(quotation_id=q.id, qty=int(qty), ctype=str(ctype)))
        db.commit()
        db.refresh(q)
        return _serialize(q)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f'Create quotation failed: {str(e)}')

@router.patch('/{qid}')
@router.put('/{qid}')
async def update_quotation(qid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(404, 'Quotation not found')
    body = await request.json()
    try:
        mapping = {
            'mode':'mode','client':'client','clientemail':'client_email','carrier':'carrier','pol':'pol','pod':'pod',
            'bookingno':'booking_no','incoterm':'incoterm','validitydate':'validity_date','status':'status','note':'note','currency':'currency'
        }
        for jk, mk in mapping.items():
            if jk in body:
                setattr(q, mk, body.get(jk) or None)
        if 'charges' in body:
            db.query(QuotationCharge).filter(QuotationCharge.quotation_id == qid).delete()
            for c in (body.get('charges') or []):
                if c.get('name'):
                    db.add(QuotationCharge(
                        quotation_id=qid,
                        name=str(c.get('name')),
                        amount=None if c.get('amount') in (None, '') else str(c.get('amount')),
                        currency=str(c.get('currency') or 'USD'),
                        unit=str(c.get('unit') or ''),
                        note=str(c.get('note') or ''),
                    ))
        if 'containers' in body:
            db.query(QuotationContainer).filter(QuotationContainer.quotation_id == qid).delete()
            for ct in (body.get('containers') or []):
                qty = ct.get('qty')
                ctype = ct.get('ctype')
                if qty and ctype:
                    db.add(QuotationContainer(quotation_id=qid, qty=int(qty), ctype=str(ctype)))
        q.updated_at = datetime.utcnow().isoformat()
        db.commit()
        db.refresh(q)
        return _serialize(q)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f'Update quotation failed: {str(e)}')

@router.delete('/{qid}')
def delete_quotation(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(404, 'Quotation not found')
    db.delete(q)
    db.commit()
    return {'ok': True}

@router.get('/{qid}/pdf')
def quotation_pdf(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(404, 'Quotation not found')
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
    except Exception as e:
        raise HTTPException(500, f'PDF dependency missing: {str(e)}')
    try:
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
        styles = getSampleStyleSheet()
        title = ParagraphStyle('title', parent=styles['Heading1'], alignment=TA_CENTER, textColor=colors.HexColor('#21808D'), fontSize=20)
        head = ParagraphStyle('head', parent=styles['Heading2'], textColor=colors.HexColor('#21808D'), fontSize=12)
        story = [Paragraph('FREIGHT QUOTATION', title), Spacer(1, 5*mm)]
        story.append(Paragraph(f'<b>Quotation Ref:</b> {q.ref}<br/><b>Valid Until:</b> {q.validity_date or "N/A"}', styles['Normal']))
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph('SHIPMENT DETAILS', head))
        t = Table([
            ['Client', q.client or 'N/A', 'Mode', q.mode or 'N/A'],
            ['POL', q.pol or 'N/A', 'POD', q.pod or 'N/A'],
            ['Carrier', q.carrier or 'N/A', 'Booking', q.booking_no or 'N/A'],
            ['Incoterm', q.incoterm or 'N/A', 'Currency', q.currency or 'USD'],
        ], colWidths=[28*mm, 62*mm, 28*mm, 62*mm])
        t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('BACKGROUND',(2,0),(2,-1),colors.whitesmoke)]))
        story.append(t)
        if q.containers:
            story.append(Spacer(1, 4*mm))
            story.append(Paragraph('CONTAINERS', head))
            ct = Table([['Qty','Type']] + [[str(c.qty), c.ctype] for c in q.containers], colWidths=[30*mm, 150*mm])
            ct.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)]))
            story.append(ct)
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph('CHARGES', head))
        totals = {}
        rows = [['Description','Amount','Currency','Unit']]
        for c in (q.charges or []):
            rows.append([c.name, c.amount or '0', c.currency or 'USD', c.unit or ''])
            try:
                totals[c.currency or 'USD'] = totals.get(c.currency or 'USD', 0) + float(c.amount or 0)
            except Exception:
                pass
        if len(rows) == 1:
            rows.append(['No charges','0',q.currency or 'USD',''])
        ch = Table(rows, colWidths=[80*mm, 30*mm, 30*mm, 40*mm])
        ch.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)]))
        story.append(ch)
        if totals:
            story.append(Spacer(1, 3*mm))
            story.append(Paragraph('<b>Total:</b> ' + ' + '.join([f'{v:,.2f} {k}' for k,v in totals.items()]), styles['Normal']))
        if q.note:
            story.append(Spacer(1, 4*mm))
            story.append(Paragraph('NOTES', head))
            story.append(Paragraph((q.note or '').replace('
','<br/>'), styles['Normal']))
        doc.build(story)
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename=quotation_{q.ref}.pdf'})
    except Exception as e:
        raise HTTPException(500, f'PDF generation failed: {str(e)}')
