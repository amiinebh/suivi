from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import SessionLocal
from auth import get_current_user
from datetime import datetime
from io import BytesIO
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/api/quotations", tags=["quotations"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def _ensure_schema(db):
    stmts = [
        "CREATE TABLE IF NOT EXISTS quotations (id SERIAL PRIMARY KEY, ref VARCHAR NOT NULL UNIQUE, mode VARCHAR DEFAULT 'Ocean', client VARCHAR, client_email VARCHAR, carrier VARCHAR, pol VARCHAR, pod VARCHAR, incoterm VARCHAR, validity_date VARCHAR, transit_days VARCHAR, status VARCHAR DEFAULT 'Pending', note TEXT, currency VARCHAR DEFAULT 'USD', created_at VARCHAR, updated_at VARCHAR)",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS client_email VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS validity_date VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS transit_days VARCHAR",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'USD'",
        "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS updated_at VARCHAR",
        "CREATE TABLE IF NOT EXISTS quotation_charges (id SERIAL PRIMARY KEY, quotation_id INTEGER REFERENCES quotations(id) ON DELETE CASCADE, name VARCHAR NOT NULL, amount VARCHAR, currency VARCHAR DEFAULT 'USD', unit VARCHAR, note VARCHAR)",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'USD'",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS unit VARCHAR",
        "ALTER TABLE quotation_charges ADD COLUMN IF NOT EXISTS note VARCHAR",
        "CREATE TABLE IF NOT EXISTS quotation_containers (id SERIAL PRIMARY KEY, quotation_id INTEGER REFERENCES quotations(id) ON DELETE CASCADE, qty INTEGER NOT NULL, ctype VARCHAR NOT NULL)",
    ]
    for s in stmts:
        try: db.execute(text(s)); db.commit()
        except Exception: db.rollback()

def _charges(db, qid):
    r = db.execute(text("SELECT id,name,amount,currency,unit,note FROM quotation_charges WHERE quotation_id=:q ORDER BY id"), {"q":qid}).fetchall()
    return [{"id":x[0],"name":x[1],"amount":x[2],"currency":x[3],"unit":x[4],"note":x[5]} for x in r]

def _containers(db, qid):
    r = db.execute(text("SELECT id,qty,ctype FROM quotation_containers WHERE quotation_id=:q ORDER BY id"), {"q":qid}).fetchall()
    return [{"id":x[0],"qty":x[1],"ctype":x[2]} for x in r]

def _serialize(db, q):
    from sqlalchemy import inspect
    cols = {c.key for c in inspect(q).mapper.column_attrs}
    return {
        "id":q.id, "ref":q.ref, "mode":getattr(q,"mode",None), "client":getattr(q,"client",None),
        "clientemail":getattr(q,"client_email",None), "carrier":getattr(q,"carrier",None),
        "pol":getattr(q,"pol",None), "pod":getattr(q,"pod",None), "incoterm":getattr(q,"incoterm",None),
        "validitydate":getattr(q,"validity_date",None), "transitdays":getattr(q,"transit_days",None),
        "status":getattr(q,"status",None), "note":getattr(q,"note",None), "currency":getattr(q,"currency",None),
        "createdat":getattr(q,"created_at",None), "updatedat":getattr(q,"updated_at",None),
        "charges":_charges(db,q.id), "containers":_containers(db,q.id),
    }

def _next_ref(db):
    year = datetime.utcnow().year
    prefix = f"QUO-{year}-"
    rows = db.execute(text("SELECT ref FROM quotations WHERE ref LIKE :p"), {"p":f"{prefix}%"}).fetchall()
    mx = 0
    for r in rows:
        try: mx = max(mx, int((r[0] or "").split("-")[-1]))
        except Exception: pass
    return f"{prefix}{str(mx+1).zfill(3)}"

def _write_children(db, qid, body):
    db.execute(text("DELETE FROM quotation_charges WHERE quotation_id=:q"), {"q":qid})
    db.execute(text("DELETE FROM quotation_containers WHERE quotation_id=:q"), {"q":qid})
    for ch in (body.get("charges") or []):
        if isinstance(ch,dict) and (ch.get("name") or "").strip():
            db.execute(text("INSERT INTO quotation_charges (quotation_id,name,amount,currency,unit,note) VALUES (:qid,:name,:amount,:currency,:unit,:note)"),
                {"qid":qid,"name":ch["name"].strip(),"amount":ch.get("amount"),"currency":ch.get("currency","USD"),"unit":ch.get("unit",""),"note":ch.get("note","")})
    for ct in (body.get("containers") or []):
        if isinstance(ct,dict) and ct.get("qty") and ct.get("ctype"):
            try: db.execute(text("INSERT INTO quotation_containers (quotation_id,qty,ctype) VALUES (:qid,:qty,:ctype)"), {"qid":qid,"qty":int(ct["qty"]),"ctype":ct["ctype"]})
            except Exception: pass

@router.get("/next-ref")
def next_ref_ep(db: Session = Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db); return {"ref": _next_ref(db)}

@router.get("/debug-schema")
def debug_schema(db: Session = Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db)
    q = [r[0] for r in db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='quotations' ORDER BY ordinal_position")).fetchall()]
    c = [r[0] for r in db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='quotation_charges' ORDER BY ordinal_position")).fetchall()]
    t = [r[0] for r in db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='quotation_containers' ORDER BY ordinal_position")).fetchall()]
    return {"quotations":q,"quotation_charges":c,"quotation_containers":t}

@router.get("")
def list_quotations(q:str="",status:str="",mode:str="", db:Session=Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db)
    from models import Quotation
    qs = db.query(Quotation)
    if q:
        like=f"%{q}%"; qs=qs.filter(Quotation.ref.ilike(like)|Quotation.client.ilike(like)|Quotation.pol.ilike(like)|Quotation.pod.ilike(like))
    if status and status not in ("","All Status"): qs=qs.filter(Quotation.status==status)
    if mode and mode not in ("","All Modes"): qs=qs.filter(Quotation.mode==mode)
    return [_serialize(db,x) for x in qs.order_by(Quotation.id.desc()).all()]

@router.get("/{qid}")
def get_quotation(qid:int, db:Session=Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db)
    from models import Quotation
    q=db.query(Quotation).filter(Quotation.id==qid).first()
    if not q: raise HTTPException(404,"Not found")
    return _serialize(db,q)

@router.post("")
async def create_quotation(request:Request, db:Session=Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db)
    body=await request.json()
    now=datetime.utcnow().isoformat()
    ref=(body.get("ref") or "").strip() or _next_ref(db)
    try:
        row=db.execute(text("""INSERT INTO quotations
            (ref,mode,client,client_email,carrier,pol,pod,incoterm,validity_date,transit_days,status,note,currency,created_at,updated_at)
            VALUES (:ref,:mode,:client,:ce,:carrier,:pol,:pod,:inc,:vd,:td,:status,:note,:cur,:now,:now) RETURNING id"""),
            {"ref":ref,"mode":body.get("mode","Ocean"),"client":body.get("client"),"ce":body.get("clientemail"),
             "carrier":body.get("carrier"),"pol":body.get("pol"),"pod":body.get("pod"),"inc":body.get("incoterm"),
             "vd":body.get("validitydate"),"td":body.get("transitdays"),"status":body.get("status","Pending"),
             "note":body.get("note"),"cur":body.get("currency","USD"),"now":now}).fetchone()
        qid=row[0]; _write_children(db,qid,body); db.commit()
        from models import Quotation
        return _serialize(db,db.query(Quotation).filter(Quotation.id==qid).first())
    except Exception as e: db.rollback(); raise HTTPException(500,f"{type(e).__name__}: {e}")

@router.patch("/{qid}")
@router.put("/{qid}")
async def update_quotation(qid:int, request:Request, db:Session=Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db)
    body=await request.json()
    now=datetime.utcnow().isoformat()
    try:
        db.execute(text("""UPDATE quotations SET mode=:mode,client=:client,client_email=:ce,carrier=:carrier,
            pol=:pol,pod=:pod,incoterm=:inc,validity_date=:vd,transit_days=:td,status=:status,
            note=:note,currency=:cur,updated_at=:now WHERE id=:id"""),
            {"mode":body.get("mode","Ocean"),"client":body.get("client"),"ce":body.get("clientemail"),
             "carrier":body.get("carrier"),"pol":body.get("pol"),"pod":body.get("pod"),"inc":body.get("incoterm"),
             "vd":body.get("validitydate"),"td":body.get("transitdays"),"status":body.get("status","Pending"),
             "note":body.get("note"),"cur":body.get("currency","USD"),"now":now,"id":qid})
        _write_children(db,qid,body); db.commit()
        from models import Quotation
        q=db.query(Quotation).filter(Quotation.id==qid).first()
        if not q: raise HTTPException(404,"Not found")
        return _serialize(db,q)
    except Exception as e: db.rollback(); raise HTTPException(500,f"{type(e).__name__}: {e}")

@router.delete("/{qid}")
def delete_quotation(qid:int, db:Session=Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db)
    try:
        db.execute(text("DELETE FROM quotation_charges WHERE quotation_id=:q"),{"q":qid})
        db.execute(text("DELETE FROM quotation_containers WHERE quotation_id=:q"),{"q":qid})
        db.execute(text("DELETE FROM quotations WHERE id=:q"),{"q":qid})
        db.commit(); return {"ok":True}
    except Exception as e: db.rollback(); raise HTTPException(500,str(e))

@router.get("/{qid}/pdf")
def quotation_pdf(qid:int, db:Session=Depends(get_db), _=Depends(get_current_user)):
    _ensure_schema(db)
    from models import Quotation
    q=db.query(Quotation).filter(Quotation.id==qid).first()
    if not q: raise HTTPException(404,"Not found")
    s=_serialize(db,q)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    buf=BytesIO()
    doc=SimpleDocTemplate(buf,pagesize=A4,topMargin=15*mm,bottomMargin=15*mm,leftMargin=15*mm,rightMargin=15*mm)
    styles=getSampleStyleSheet()
    title=ParagraphStyle('t',parent=styles['Heading1'],alignment=TA_CENTER,textColor=colors.HexColor('#21808D'),fontSize=20)
    head=ParagraphStyle('h',parent=styles['Heading2'],textColor=colors.HexColor('#21808D'),fontSize=12)
    story=[Paragraph('FREIGHT QUOTATION',title),Spacer(1,5*mm),
           Paragraph(f'<b>Ref:</b> {s["ref"]}  &nbsp;&nbsp; <b>Valid Until:</b> {s["validitydate"] or "N/A"}  &nbsp;&nbsp; <b>Transit:</b> {s["transitdays"] or "N/A"} days',styles['Normal']),
           Spacer(1,4*mm),Paragraph('SHIPMENT DETAILS',head)]
    tbl=Table([['Client',s['client']or'N/A','Mode',s['mode']or'N/A'],['POL',s['pol']or'N/A','POD',s['pod']or'N/A'],
               ['Carrier',s['carrier']or'N/A','Currency',s['currency']or'USD'],['Incoterm',s['incoterm']or'N/A','Status',s['status']or'Pending']],
               colWidths=[28*mm,62*mm,28*mm,62*mm])
    tbl.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('BACKGROUND',(2,0),(2,-1),colors.whitesmoke)]))
    story.append(tbl)
    if s['containers']:
        story+=[Spacer(1,4*mm),Paragraph('CONTAINERS',head)]
        ct=Table([['Qty','Type']]+[[str(c['qty']),c['ctype']] for c in s['containers']],colWidths=[30*mm,150*mm])
        ct.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)]))
        story.append(ct)
    story+=[Spacer(1,4*mm),Paragraph('CHARGES',head)]
    rows=[['Description','Amount','Currency','Unit']]; totals={}
    for c in s['charges']:
        rows.append([c['name'],c['amount']or'0',c['currency']or'USD',c['unit']or''])
        try: totals[c['currency']or'USD']=totals.get(c['currency']or'USD',0)+float(c['amount']or 0)
        except: pass
    if len(rows)==1: rows.append(['No charges','0',s['currency']or'USD',''])
    ch=Table(rows,colWidths=[80*mm,30*mm,30*mm,40*mm])
    ch.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)]))
    story.append(ch)
    if totals: story+=[Spacer(1,3*mm),Paragraph('<b>Total: </b>'+' + '.join([f'{v:,.2f} {k}' for k,v in totals.items()]),styles['Normal'])]
    if s['note']: story+=[Spacer(1,4*mm),Paragraph('NOTES',head),Paragraph((s['note']or'').replace('\n','<br/>'),styles['Normal'])]
    doc.build(story); buf.seek(0)
    return Response(content=buf.getvalue(),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename=quotation_{s["ref"]}.pdf'})
