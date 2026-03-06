from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal
from models import Quotation
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

def _ensure_quotation_schema(db):
    fixes = [
        "CREATE TABLE IF NOT EXISTS quotations (id SERIAL PRIMARY KEY, ref VARCHAR NOT NULL UNIQUE, mode VARCHAR DEFAULT 'Ocean', client VARCHAR, client_email VARCHAR, carrier VARCHAR, pol VARCHAR, pod VARCHAR, incoterm VARCHAR, validity_date VARCHAR, status VARCHAR DEFAULT 'Pending', note TEXT, currency VARCHAR DEFAULT 'USD', created_at VARCHAR, updated_at VARCHAR)",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS client_email VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS validity_date VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'USD'",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS updated_at VARCHAR",
        "CREATE TABLE IF NOT EXISTS quotation_charges (id SERIAL PRIMARY KEY, quotation_id INTEGER REFERENCES quotations(id) ON DELETE CASCADE, name VARCHAR NOT NULL, amount VARCHAR, currency VARCHAR, unit VARCHAR, note VARCHAR)",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS currency VARCHAR",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS unit VARCHAR",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS note VARCHAR",
        "CREATE TABLE IF NOT EXISTS quotation_containers (id SERIAL PRIMARY KEY, quotation_id INTEGER REFERENCES quotations(id) ON DELETE CASCADE, qty INTEGER NOT NULL, ctype VARCHAR NOT NULL)",
    ]
    for sql in fixes:
        try:
            db.execute(text(sql))
            db.commit()
        except Exception:
            db.rollback()

def _colset(db, table):
    rows = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"), {"t": table}).fetchall()
    return set(r[0] for r in rows)

def _charges_for(db, qid):
    cols = _colset(db, 'quotation_charges')
    sel = ['id', 'name', 'amount']
    sel.append('currency' if 'currency' in cols else 'NULL as currency')
    sel.append('unit' if 'unit' in cols else 'NULL as unit')
    sel.append('note' if 'note' in cols else 'NULL as note')
    rows = db.execute(text(f"SELECT {', '.join(sel)} FROM quotation_charges WHERE quotation_id=:qid ORDER BY id ASC"), {'qid': qid}).fetchall()
    return [{'id': r[0], 'name': r[1], 'amount': r[2], 'currency': r[3], 'unit': r[4], 'note': r[5]} for r in rows]

def _containers_for(db, qid):
    rows = db.execute(text("SELECT id, qty, ctype FROM quotation_containers WHERE quotation_id=:qid ORDER BY id ASC"), {'qid': qid}).fetchall()
    return [{'id': r[0], 'qty': r[1], 'ctype': r[2]} for r in rows]

def _serialize(db, q):
    return {
        'id': q.id, 'ref': q.ref, 'mode': getattr(q,'mode',None), 'client': getattr(q,'client',None),
        'clientemail': getattr(q,'client_email',None), 'carrier': getattr(q,'carrier',None), 'pol': getattr(q,'pol',None),
        'pod': getattr(q,'pod',None), 'incoterm': getattr(q,'incoterm',None), 'validitydate': getattr(q,'validity_date',None),
        'status': getattr(q,'status',None), 'note': getattr(q,'note',None), 'currency': getattr(q,'currency',None),
        'createdat': getattr(q,'created_at',None), 'updatedat': getattr(q,'updated_at',None),
        'charges': _charges_for(db, q.id), 'containers': _containers_for(db, q.id),
    }

def _next_ref(db):
    _ensure_quotation_schema(db)
    year = datetime.utcnow().year
    prefix = f"QUO-{year}-"
    rows = db.execute(text("SELECT ref FROM quotations WHERE ref LIKE :p"), {'p': f'{prefix}%'}).fetchall()
    mx = 0
    for r in rows:
        try: mx = max(mx, int((r[0] or '').split('-')[-1]))
        except Exception: pass
    return f"{prefix}{str(mx+1).zfill(3)}"

@router.get('/next-ref')
def next_ref(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return {'ref': _next_ref(db)}

@router.get('/debug-schema')
def debug_schema(db: Session = Depends(get_db), current=Depends(get_current_user)):
    _ensure_quotation_schema(db)
    qcols = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='quotations' ORDER BY ordinal_position")).fetchall()
    ccols = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='quotation_charges' ORDER BY ordinal_position")).fetchall()
    tcols = db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='quotation_containers' ORDER BY ordinal_position")).fetchall()
    return {'quotations':[x[0] for x in qcols], 'quotation_charges':[x[0] for x in ccols], 'quotation_containers':[x[0] for x in tcols]}

@router.get('')
def list_quotations(q: str = '', status: str = '', mode: str = '', db: Session = Depends(get_db), current=Depends(get_current_user)):
    _ensure_quotation_schema(db)
    qs = db.query(Quotation)
    if q:
        like = f"%{q}%"
        qs = qs.filter(Quotation.ref.ilike(like) | Quotation.client.ilike(like) | Quotation.pol.ilike(like) | Quotation.pod.ilike(like))
    if status and status not in ('', 'All Status'):
        qs = qs.filter(Quotation.status == status)
    if mode and mode not in ('', 'All Modes'):
        qs = qs.filter(Quotation.mode == mode)
    return [_serialize(db, x) for x in qs.order_by(Quotation.id.desc()).all()]

@router.get('/{qid}')
def get_quotation(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    _ensure_quotation_schema(db)
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q: raise HTTPException(404, 'Quotation not found')
    return _serialize(db, q)

@router.post('')
async def create_quotation(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    _ensure_quotation_schema(db)
    body = await request.json()
    ref = (body.get('ref') or '').strip() or _next_ref(db)
    now = datetime.utcnow().isoformat()
    qcols = _colset(db, 'quotations')
    insert_cols = ['ref']
    params = {'ref': ref}
    mapping = [
        ('mode', body.get('mode') or 'Ocean'), ('client', body.get('client') or None), ('client_email', body.get('clientemail') or None),
        ('carrier', body.get('carrier') or None), ('pol', body.get('pol') or None), ('pod', body.get('pod') or None),
        ('incoterm', body.get('incoterm') or None), ('validity_date', body.get('validitydate') or None), ('status', body.get('status') or 'Pending'),
        ('note', body.get('note') or None), ('currency', body.get('currency') or 'USD'), ('created_at', now), ('updated_at', now),
    ]
    for col, val in mapping:
        if col in qcols:
            insert_cols.append(col); params[col] = val
    try:
        row = db.execute(text(f"INSERT INTO quotations ({', '.join(insert_cols)}) VALUES ({', '.join(':'+c for c in insert_cols)}) RETURNING id"), params).fetchone()
        qid = row[0]
        ccols = _colset(db, 'quotation_charges')
        for c in (body.get('charges') or []):
            if isinstance(c, dict) and (c.get('name') or '').strip():
                cols = ['quotation_id','name']
                vals = {'quotation_id': qid, 'name': str(c.get('name')).strip()}
                if 'amount' in ccols: cols.append('amount'); vals['amount'] = None if c.get('amount') in (None,'') else str(c.get('amount'))
                if 'currency' in ccols: cols.append('currency'); vals['currency'] = str(c.get('currency') or 'USD')
                if 'unit' in ccols: cols.append('unit'); vals['unit'] = str(c.get('unit') or '')
                if 'note' in ccols: cols.append('note'); vals['note'] = str(c.get('note') or '')
                db.execute(text(f"INSERT INTO quotation_charges ({', '.join(cols)}) VALUES ({', '.join(':'+x for x in cols)})"), vals)
        tcols = _colset(db, 'quotation_containers')
        for ct in (body.get('containers') or []):
            if isinstance(ct, dict) and ct.get('qty') and ct.get('ctype') and {'quotation_id','qty','ctype'}.issubset(tcols):
                try: qty = int(ct.get('qty'))
                except Exception: continue
                db.execute(text("INSERT INTO quotation_containers (quotation_id, qty, ctype) VALUES (:quotation_id,:qty,:ctype)"), {'quotation_id': qid, 'qty': qty, 'ctype': str(ct.get('ctype'))})
        db.commit()
        q = db.query(Quotation).filter(Quotation.id == qid).first()
        return _serialize(db, q)
    except Exception as e:
        db.rollback(); raise HTTPException(500, f'{type(e).__name__}: {str(e)}')

@router.patch('/{qid}')
@router.put('/{qid}')
async def update_quotation(qid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    _ensure_quotation_schema(db)
    body = await request.json()
    qcols = _colset(db, 'quotations')
    sets=[]; params={'id': qid}
    for col, val in [('mode', body.get('mode') or 'Ocean'), ('client', body.get('client') or None), ('client_email', body.get('clientemail') or None), ('carrier', body.get('carrier') or None), ('pol', body.get('pol') or None), ('pod', body.get('pod') or None), ('incoterm', body.get('incoterm') or None), ('validity_date', body.get('validitydate') or None), ('status', body.get('status') or 'Pending'), ('note', body.get('note') or None), ('currency', body.get('currency') or 'USD'), ('updated_at', datetime.utcnow().isoformat())]:
        if col in qcols: sets.append(f"{col}=:{col}"); params[col]=val
    try:
        if sets: db.execute(text(f"UPDATE quotations SET {', '.join(sets)} WHERE id=:id"), params)
        db.execute(text("DELETE FROM quotation_charges WHERE quotation_id=:qid"), {'qid': qid})
        db.execute(text("DELETE FROM quotation_containers WHERE quotation_id=:qid"), {'qid': qid})
        ccols = _colset(db, 'quotation_charges')
        for c in (body.get('charges') or []):
            if isinstance(c, dict) and (c.get('name') or '').strip():
                cols = ['quotation_id','name']
                vals = {'quotation_id': qid, 'name': str(c.get('name')).strip()}
                if 'amount' in ccols: cols.append('amount'); vals['amount'] = None if c.get('amount') in (None,'') else str(c.get('amount'))
                if 'currency' in ccols: cols.append('currency'); vals['currency'] = str(c.get('currency') or 'USD')
                if 'unit' in ccols: cols.append('unit'); vals['unit'] = str(c.get('unit') or '')
                if 'note' in ccols: cols.append('note'); vals['note'] = str(c.get('note') or '')
                db.execute(text(f"INSERT INTO quotation_charges ({', '.join(cols)}) VALUES ({', '.join(':'+x for x in cols)})"), vals)
        tcols = _colset(db, 'quotation_containers')
        for ct in (body.get('containers') or []):
            if isinstance(ct, dict) and ct.get('qty') and ct.get('ctype') and {'quotation_id','qty','ctype'}.issubset(tcols):
                try: qty = int(ct.get('qty'))
                except Exception: continue
                db.execute(text("INSERT INTO quotation_containers (quotation_id, qty, ctype) VALUES (:quotation_id,:qty,:ctype)"), {'quotation_id': qid, 'qty': qty, 'ctype': str(ct.get('ctype'))})
        db.commit()
        q = db.query(Quotation).filter(Quotation.id == qid).first()
        return _serialize(db, q)
    except Exception as e:
        db.rollback(); raise HTTPException(500, f'{type(e).__name__}: {str(e)}')

@router.delete('/{qid}')
def delete_quotation(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    _ensure_quotation_schema(db)
    try:
        db.execute(text("DELETE FROM quotation_charges WHERE quotation_id=:qid"), {'qid': qid})
        db.execute(text("DELETE FROM quotation_containers WHERE quotation_id=:qid"), {'qid': qid})
        db.execute(text("DELETE FROM quotations WHERE id=:qid"), {'qid': qid})
        db.commit(); return {'ok': True}
    except Exception as e:
        db.rollback(); raise HTTPException(500, f'{type(e).__name__}: {str(e)}')

@router.get('/{qid}/pdf')
def quotation_pdf(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    _ensure_quotation_schema(db)
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q: raise HTTPException(404, 'Quotation not found')
    charges = _charges_for(db, qid); containers = _containers_for(db, qid)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    buf = BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet(); title = ParagraphStyle('title', parent=styles['Heading1'], alignment=TA_CENTER, textColor=colors.HexColor('#21808D'), fontSize=20); head = ParagraphStyle('head', parent=styles['Heading2'], textColor=colors.HexColor('#21808D'), fontSize=12)
    story = [Paragraph('FREIGHT QUOTATION', title), Spacer(1, 5*mm), Paragraph(f'<b>Quotation Ref:</b> {q.ref}<br/><b>Valid Until:</b> {getattr(q,"validity_date",None) or "N/A"}', styles['Normal']), Spacer(1, 4*mm), Paragraph('SHIPMENT DETAILS', head)]
    t = Table([['Client', getattr(q,'client',None) or 'N/A', 'Mode', getattr(q,'mode',None) or 'N/A'], ['POL', getattr(q,'pol',None) or 'N/A', 'POD', getattr(q,'pod',None) or 'N/A'], ['Carrier', getattr(q,'carrier',None) or 'N/A', 'Currency', getattr(q,'currency',None) or 'USD'], ['Incoterm', getattr(q,'incoterm',None) or 'N/A', 'Status', getattr(q,'status',None) or 'Pending']], colWidths=[28*mm, 62*mm, 28*mm, 62*mm])
    t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('BACKGROUND',(2,0),(2,-1),colors.whitesmoke)])); story.append(t)
    if containers:
        story += [Spacer(1, 4*mm), Paragraph('CONTAINERS', head)]
        ct = Table([['Qty','Type']] + [[str(c['qty']), c['ctype']] for c in containers], colWidths=[30*mm, 150*mm])
        ct.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)])); story.append(ct)
    story += [Spacer(1, 4*mm), Paragraph('CHARGES', head)]
    totals={}; rows=[['Description','Amount','Currency','Unit']]
    for c in charges:
        rows.append([c['name'], c['amount'] or '0', c['currency'] or 'USD', c['unit'] or ''])
        try: totals[c['currency'] or 'USD'] = totals.get(c['currency'] or 'USD', 0) + float(c['amount'] or 0)
        except Exception: pass
    if len(rows)==1: rows.append(['No charges','0',getattr(q,'currency',None) or 'USD',''])
    ch = Table(rows, colWidths=[80*mm, 30*mm, 30*mm, 40*mm])
    ch.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)])); story.append(ch)
    if totals: story += [Spacer(1,3*mm), Paragraph('<b>Total:</b> ' + ' + '.join([f'{v:,.2f} {k}' for k,v in totals.items()]), styles['Normal'])]
    if getattr(q,'note',None): story += [Spacer(1,4*mm), Paragraph('NOTES', head), Paragraph((q.note or '').replace('\\n','<br/>'), styles['Normal'])]
    doc.build(story); buf.seek(0)
    return Response(content=buf.getvalue(), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename=quotation_{q.ref}.pdf'})
