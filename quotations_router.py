from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Quotation, QuotationCharge
from auth import get_current_user
from datetime import datetime

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
        "etd": q.etd, "eta": q.eta, "bookingno": q.booking_no,
        "incoterm": q.incoterm, "status": q.status, "note": q.note,
        "shipper": q.shipper, "consignee": q.consignee, "currency": q.currency,
        "createdat": q.created_at, "updatedat": q.updated_at,
        "charges": [{"id": c.id, "name": c.name, "amount": c.amount,
                     "currency": c.currency, "unit": c.unit, "note": c.note}
                    for c in (q.charges or [])],
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
                  etd=body.get("etd"), eta=body.get("eta"),
                  booking_no=body.get("bookingno"), incoterm=body.get("incoterm"),
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
            "carrier":"carrier","pol":"pol","pod":"pod","etd":"etd","eta":"eta",
            "bookingno":"booking_no","incoterm":"incoterm","status":"status",
            "note":"note","shipper":"shipper","consignee":"consignee","currency":"currency"}
    for jk, ma in fmap.items():
        if jk in body: setattr(q, ma, body[jk] or None)
    if "charges" in body:
        db.query(QuotationCharge).filter(QuotationCharge.quotation_id == qid).delete()
        for c in (body["charges"] or []):
            if c.get("name"):
                db.add(QuotationCharge(quotation_id=qid, name=c["name"],
                                       amount=c.get("amount"), currency=c.get("currency","USD"),
                                       unit=c.get("unit"), note=c.get("note")))
    q.updated_at = datetime.utcnow().isoformat()
    db.commit(); db.refresh(q)
    return _s(q)

@router.delete("/{qid}")
def delete_quotation(qid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q: raise HTTPException(404, "Quotation not found")
    db.delete(q); db.commit()
    return {"ok": True}
