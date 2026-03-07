from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal
from auth import get_current_user
from datetime import datetime
from io import BytesIO

router = APIRouter(prefix="/api/quotations", tags=["quotations"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def _schema(db):
    stmts = [
        "CREATE TABLE IF NOT EXISTS quotations (id SERIAL PRIMARY KEY, ref VARCHAR NOT NULL, mode VARCHAR DEFAULT 'Ocean', client VARCHAR, client_email VARCHAR, carrier VARCHAR, pol VARCHAR, pod VARCHAR, incoterm VARCHAR, validity_date VARCHAR, transit_days VARCHAR, status VARCHAR DEFAULT 'Pending', note TEXT, currency VARCHAR DEFAULT 'USD', created_at VARCHAR, updated_at VARCHAR)",
        "CREATE UNIQUE INDEX IF NOT EXISTS quotations_ref_uq ON quotations(ref)",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS client_email VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS validity_date VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS transit_days VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'USD'",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS updated_at VARCHAR",
        "CREATE TABLE IF NOT EXISTS quotation_charges (id SERIAL PRIMARY KEY, quotation_id INTEGER REFERENCES quotations(id) ON DELETE CASCADE, name VARCHAR NOT NULL, amount VARCHAR, currency VARCHAR DEFAULT 'USD', unit VARCHAR)",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'USD'",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS unit VARCHAR",
        "CREATE TABLE IF NOT EXISTS quotation_containers (id SERIAL PRIMARY KEY, quotation_id INTEGER REFERENCES quotations(id) ON DELETE CASCADE, qty INTEGER NOT NULL, ctype VARCHAR NOT NULL)",
    ]
    for s in stmts:
        try: db.execute(text(s)); db.commit()
        except Exception: db.rollback()

def _charges(db, qid):
    rows = db.execute(text("SELECT id,name,amount,currency,unit FROM quotation_charges WHERE quotation_id=:q ORDER BY id"), {"q": qid}).fetchall()
    return [{"id": r[0], "name": r[1], "amount": r[2], "currency": r[3], "unit": r[4]} for r in rows]

def _containers(db, qid):
    rows = db.execute(text("SELECT id,qty,ctype FROM quotation_containers WHERE quotation_id=:q ORDER BY id"), {"q": qid}).fetchall()
    return [{"id": r[0], "qty": r[1], "ctype": r[2]} for r in rows]

def _ser(db, r):
    return {"id":r[0],"ref":r[1],"mode":r[2],"client":r[3],"clientemail":r[4],"carrier":r[5],
            "pol":r[6],"pod":r[7],"incoterm":r[8],"validitydate":r[9],"transitdays":r[10],
            "status":r[11],"note":r[12],"currency":r[13],
            "charges":_charges(db,r[0]),"containers":_containers(db,r[0])}

def _next_ref(db):
    yr = datetime.utcnow().year
    pfx = f"QUO-{yr}-"
    rows = db.execute(text("SELECT ref FROM quotations WHERE ref LIKE :p"), {"p": f"{pfx}%"}).fetchall()
    mx = 0
    for row in rows:
        try: mx = max(mx, int((row[0] or "").split("-")[-1]))
        except: pass
    return f"{pfx}{str(mx+1).zfill(3)}"

def _write_children(db, qid, body):
    db.execute(text("DELETE FROM quotation_charges WHERE quotation_id=:q"), {"q": qid})
    db.execute(text("DELETE FROM quotation_containers WHERE quotation_id=:q"), {"q": qid})
    db.commit()
    for ch in (body.get("charges") or []):
        if isinstance(ch, dict) and (ch.get("name") or "").strip():
            db.execute(text("INSERT INTO quotation_charges (quotation_id,name,amount,currency,unit) VALUES (:q,:n,:a,:c,:u)"),
                {"q": qid, "n": ch["name"].strip(), "a": str(ch.get("amount") or ""), "c": ch.get("currency","USD"), "u": ch.get("unit","Per BL")})
    for ct in (body.get("containers") or []):
        if isinstance(ct, dict) and ct.get("qty") and ct.get("ctype"):
            try:
                db.execute(text("INSERT INTO quotation_containers (quotation_id,qty,ctype) VALUES (:q,:qty,:ct)"),
                    {"q": qid, "qty": int(ct["qty"]), "ct": ct["ctype"]})
            except: pass
    db.commit()

@router.get("/next-ref")
def next_ref(db: Session = Depends(get_db), _=Depends(get_current_user)):
    _schema(db); return {"ref": _next_ref(db)}

@router.get("")
def list_q(q: str="", status: str="", mode: str="", db: Session=Depends(get_db), _=Depends(get_current_user)):
    _schema(db)
    where = "WHERE 1=1"; params = {}
    if q: where += " AND (ref ILIKE :q OR client ILIKE :q OR pol ILIKE :q OR pod ILIKE :q)"; params["q"] = f"%{q}%"
    if status and status not in ("","All Status"): where += " AND status=:status"; params["status"] = status
    if mode and mode not in ("","All Modes"): where += " AND mode=:mode"; params["mode"] = mode
    rows = db.execute(text(f"SELECT id,ref,mode,client,client_email,carrier,pol,pod,incoterm,validity_date,transit_days,status,note,currency FROM quotations {where} ORDER BY id DESC"), params).fetchall()
    return [_ser(db, r) for r in rows]

@router.get("/{qid}")
def get_q(qid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    _schema(db)
    r = db.execute(text("SELECT id,ref,mode,client,client_email,carrier,pol,pod,incoterm,validity_date,transit_days,status,note,currency FROM quotations WHERE id=:id"), {"id": qid}).fetchone()
    if not r: raise HTTPException(404, "Not found")
    return _ser(db, r)

@router.post("")
async def create_q(request: Request, db: Session=Depends(get_db), _=Depends(get_current_user)):
    _schema(db)
    body = await request.json()
    now = datetime.utcnow().isoformat()
    ref = (body.get("ref") or "").strip() or _next_ref(db)
    try:
        row = db.execute(text("""
            INSERT INTO quotations (ref,mode,client,client_email,carrier,pol,pod,incoterm,validity_date,transit_days,status,note,currency,created_at,updated_at)
            VALUES (:ref,:mode,:client,:ce,:carrier,:pol,:pod,:inc,:vd,:td,:status,:note,:cur,:now,:now) RETURNING id"""),
            {"ref":ref,"mode":body.get("mode","Ocean"),"client":body.get("client"),"ce":body.get("clientemail"),
             "carrier":body.get("carrier"),"pol":body.get("pol"),"pod":body.get("pod"),"inc":body.get("incoterm"),
             "vd":body.get("validitydate"),"td":body.get("transitdays"),"status":body.get("status","Pending"),
             "note":body.get("note"),"cur":body.get("currency","USD"),"now":now}).fetchone()
        qid = row[0]; _write_children(db, qid, body); db.commit()
        r = db.execute(text("SELECT id,ref,mode,client,client_email,carrier,pol,pod,incoterm,validity_date,transit_days,status,note,currency FROM quotations WHERE id=:id"), {"id": qid}).fetchone()
        return _ser(db, r)
    except Exception as e: db.rollback(); raise HTTPException(500, f"{type(e).__name__}: {e}")

@router.patch("/{qid}")
@router.put("/{qid}")
async def update_q(qid: int, request: Request, db: Session=Depends(get_db), _=Depends(get_current_user)):
    _schema(db)
    body = await request.json()
    now = datetime.utcnow().isoformat()
    try:
        db.execute(text("""UPDATE quotations SET mode=:mode,client=:client,client_email=:ce,carrier=:carrier,
            pol=:pol,pod=:pod,incoterm=:inc,validity_date=:vd,transit_days=:td,status=:status,
            note=:note,currency=:cur,updated_at=:now WHERE id=:id"""),
            {"mode":body.get("mode","Ocean"),"client":body.get("client"),"ce":body.get("clientemail"),
             "carrier":body.get("carrier"),"pol":body.get("pol"),"pod":body.get("pod"),"inc":body.get("incoterm"),
             "vd":body.get("validitydate"),"td":body.get("transitdays"),"status":body.get("status","Pending"),
             "note":body.get("note"),"cur":body.get("currency","USD"),"now":now,"id":qid})
        _write_children(db, qid, body)
        r = db.execute(text("SELECT id,ref,mode,client,client_email,carrier,pol,pod,incoterm,validity_date,transit_days,status,note,currency FROM quotations WHERE id=:id"), {"id": qid}).fetchone()
        if not r: raise HTTPException(404, "Not found")
        return _ser(db, r)
    except Exception as e: db.rollback(); raise HTTPException(500, f"{type(e).__name__}: {e}")

@router.delete("/{qid}")
def delete_q(qid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    _schema(db)
    try:
        db.execute(text("DELETE FROM quotation_charges WHERE quotation_id=:q"), {"q": qid})
        db.execute(text("DELETE FROM quotation_containers WHERE quotation_id=:q"), {"q": qid})
        db.execute(text("DELETE FROM quotations WHERE id=:q"), {"q": qid})
        db.commit(); return {"ok": True}
    except Exception as e: db.rollback(); raise HTTPException(500, str(e))

@router.get("/{qid}/pdf")
def quotation_pdf(qid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    _schema(db)
    r = db.execute(text("SELECT id,ref,mode,client,client_email,carrier,pol,pod,incoterm,validity_date,transit_days,status,note,currency FROM quotations WHERE id=:id"), {"id": qid}).fetchone()
    if not r: raise HTTPException(404, "Not found")
    s = _ser(db, r)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
        styles = getSampleStyleSheet()
        title_s = ParagraphStyle('t', parent=styles['Heading1'], alignment=TA_CENTER, textColor=colors.HexColor('#21808D'), fontSize=18)
        head_s = ParagraphStyle('h', parent=styles['Heading2'], textColor=colors.HexColor('#21808D'), fontSize=11)
        story = [Paragraph('FREIGHT QUOTATION', title_s), Spacer(1,4*mm),
                 Paragraph(f'<b>Ref:</b> {s["ref"]} &nbsp;&nbsp; <b>Valid:</b> {s["validitydate"] or "N/A"} &nbsp;&nbsp; <b>Transit:</b> {s["transitdays"] or "N/A"} days', styles['Normal']),
                 Spacer(1,4*mm), Paragraph('SHIPMENT DETAILS', head_s)]
        info = Table([['Client', s['client'] or 'N/A', 'Mode', s['mode'] or 'N/A'],
                      ['POL', s['pol'] or 'N/A', 'POD', s['pod'] or 'N/A'],
                      ['Carrier', s['carrier'] or 'N/A', 'Currency', s['currency'] or 'USD'],
                      ['Incoterm', s['incoterm'] or 'N/A', 'Status', s['status'] or 'Pending']],
                     colWidths=[28*mm, 62*mm, 28*mm, 62*mm])
        info.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),
            ('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('BACKGROUND',(2,0),(2,-1),colors.whitesmoke)]))
        story.append(info)
        if s['containers']:
            story += [Spacer(1,4*mm), Paragraph('CONTAINERS', head_s)]
            ct = Table([['Qty','Type']]+[[str(c['qty']), c['ctype']] for c in s['containers']], colWidths=[30*mm,150*mm])
            ct.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)]))
            story.append(ct)
        story += [Spacer(1,4*mm), Paragraph('CHARGES', head_s)]
        ch_rows = [['Description','Amount','Currency','Unit']]
        totals = {}
        for c in s['charges']:
            ch_rows.append([c['name'], c['amount'] or '0', c['currency'] or 'USD', c['unit'] or ''])
            try: totals[c['currency'] or 'USD'] = totals.get(c['currency'] or 'USD', 0) + float(c['amount'] or 0)
            except: pass
        if len(ch_rows) == 1: ch_rows.append(['No charges', '0', s['currency'] or 'USD', ''])
        ch = Table(ch_rows, colWidths=[80*mm, 30*mm, 30*mm, 40*mm])
        ch.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)]))
        story.append(ch)
        if totals: story += [Spacer(1,3*mm), Paragraph('<b>Total: </b>' + ' + '.join([f'{v:,.2f} {k}' for k,v in totals.items()]), styles['Normal'])]
        if s['note']: story += [Spacer(1,4*mm), Paragraph('NOTES', head_s), Paragraph((s['note'] or '').replace('\n','<br/>'), styles['Normal'])]
        doc.build(story); buf.seek(0)
        return Response(content=buf.getvalue(), media_type='application/pdf',
                        headers={'Content-Disposition': f'attachment; filename=quotation_{s["ref"]}.pdf'})
    except ImportError:
        raise HTTPException(500, "reportlab not installed")
