from sqlalchemy.orm import Session
from sqlalchemy import or_
import models, schemas

def get_shipments(db: Session, search="", status="", mode=""):
    q = db.query(models.Shipment)
    if search:
        s = f"%{search}%"
        q = q.filter(or_(
            models.Shipment.ref.ilike(s), models.Shipment.ref2.ilike(s),
            models.Shipment.client.ilike(s), models.Shipment.carrier.ilike(s),
            models.Shipment.vessel.ilike(s), models.Shipment.booking_no.ilike(s),
        ))
    if status: q = q.filter(models.Shipment.status == status)
    if mode:   q = q.filter(models.Shipment.mode == mode)
    return q.order_by(models.Shipment.id.desc()).all()

def get_shipment(db, ref): return db.query(models.Shipment).filter(models.Shipment.ref==ref).first()
def get_shipment_by_id(db, sid): return db.query(models.Shipment).filter(models.Shipment.id==sid).first()

def create_shipment(db, s: schemas.ShipmentCreate):
    try:
        obj = models.Shipment(**s.dict())
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj
    except Exception as e:
        db.rollback()
        raise e

def update_shipment(db, sid, data: schemas.ShipmentUpdate):
    obj = get_shipment_by_id(db, sid)
    if not obj: return None
    for k, v in data.dict(exclude_none=True).items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj); return obj

def delete_shipment(db, sid):
    obj = get_shipment_by_id(db, sid)
    if obj: db.delete(obj); db.commit()

def add_event(db, shipment_id, location, description, status=None):
    from datetime import datetime
    ev = models.ShipmentEvent(shipment_id=shipment_id, timestamp=datetime.utcnow().isoformat(),
        location=location, description=description, status=status)
    db.add(ev); db.commit(); db.refresh(ev); return ev

def add_comment(db, shipment_id, data: schemas.CommentCreate):
    from datetime import datetime
    c = models.ShipmentComment(shipment_id=shipment_id,
        timestamp=datetime.utcnow().isoformat(), author=data.author, text=data.text)
    db.add(c); db.commit(); db.refresh(c); return c

def get_stats(db):
    all_s = db.query(models.Shipment).all()
    by_status, by_mode = {}, {}
    for s in all_s:
        by_status[s.status] = by_status.get(s.status,0)+1
        by_mode[s.mode]     = by_mode.get(s.mode,0)+1
    delayed_ids = [s.id for s in all_s if s.status=="Delayed"]
    return {"total": len(all_s), "by_status": by_status, "by_mode": by_mode,
            "delayed_count": len(delayed_ids)}
