"""
/api/quotations — CRUD router.
In main.py add:
    from quotations_router import router as quot_router
    app.include_router(quot_router)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Quotation
from auth import get_current_user
from datetime import datetime

router = APIRouter(prefix="/api/quotations", tags=["quotations"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
    if not q:
        raise HTTPException(404, "Quotation not found")
    return _s(q)


@router.post("")
async def create_quotation(request: Request, db: Session = Depends(get_db),
                           current=Depends(get_current_user)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    ref = (body.get("ref") or "").strip()
    if not ref:
        raise HTTPException(400, "Quotation Ref is required")
    if db.query(Quotation).filter(Quotation.ref == ref).first():
        raise HTTPException(400, "Ref already exists")
    now = datetime.utcnow().isoformat()
    q = Quotation(ref=ref, mode=body.get("mode") or "Ocean",
                  client=body.get("client") or None, clientemail=body.get("clientemail") or None,
                  carrier=body.get("carrier") or None, pol=body.get("pol") or None,
                  pod=body.get("pod") or None, etd=body.get("etd") or None,
                  eta=body.get("eta") or None, bookingno=body.get("bookingno") or None,
                  incoterm=body.get("incoterm") or None, status=body.get("status") or "Pending",
                  note=body.get("note") or None, shipper=body.get("shipper") or None,
                  consignee=body.get("consignee") or None, createdat=now, updatedat=now)
    db.add(q); db.commit(); db.refresh(q)
    return _s(q)


@router.put("/{qid}")
@router.patch("/{qid}")
async def update_quotation(qid: int, request: Request, db: Session = Depends(get_db),
                           current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    body = await request.json()
    for field in ["mode","client","clientemail","carrier","pol","pod","etd","eta",
                  "bookingno","incoterm","status","note","shipper","consignee"]:
        if field in body:
            setattr(q, field, body[field] or None)
    q.updatedat = datetime.utcnow().isoformat()
    db.commit(); db.refresh(q)
    return _s(q)


@router.delete("/{qid}")
def delete_quotation(qid: int, db: Session = Depends(get_db),
                     current=Depends(get_current_user)):
    q = db.query(Quotation).filter(Quotation.id == qid).first()
    if not q:
        raise HTTPException(404, "Quotation not found")
    db.delete(q); db.commit()
    return {"ok": True}


def _s(q: Quotation) -> dict:
    return {"id": q.id, "ref": q.ref, "mode": q.mode, "client": q.client,
            "clientemail": q.clientemail, "carrier": q.carrier, "pol": q.pol,
            "pod": q.pod, "etd": q.etd, "eta": q.eta, "bookingno": q.bookingno,
            "incoterm": q.incoterm, "status": q.status, "note": q.note,
            "shipper": q.shipper, "consignee": q.consignee,
            "createdat": q.createdat, "updatedat": q.updatedat}
