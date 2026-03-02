from sqlalchemy.orm import Session
from sqlalchemy import or_, text, func
import models, schemas
import time

def get_shipments(db: Session, search: str = "", status: str = "", mode: str = ""):
    q = db.query(models.Shipment)
    if search:
        search = f"%{search}%"
        q = q.filter(
            or_(
                models.Shipment.ref.ilike(search),
                models.Shipment.ref2.ilike(search),
                models.Shipment.booking_no.ilike(search),
                models.Shipment.client.ilike(search),
                models.Shipment.quotation_number.ilike(search)
            )
        )
    if status and status != "All Status":
        q = q.filter(models.Shipment.status.ilike(status))
    if mode and mode != "All Modes":
        q = q.filter(models.Shipment.mode.ilike(mode))
    return q.order_by(models.Shipment.id.desc()).all()

def create_shipment(db: Session, s: schemas.ShipmentCreate):
    db_s = models.Shipment(**s.model_dump())
    db.add(db_s)
    db.commit()
    db.refresh(db_s)
    return db_s

def get_shipment(db: Session, ref: str):
    return db.query(models.Shipment).filter(models.Shipment.ref == ref).first()

def get_shipment_by_id(db: Session, sid: int):
    return db.query(models.Shipment).filter(models.Shipment.id == sid).first()

def update_shipment(db: Session, sid: int, data: schemas.ShipmentUpdate):
    s = get_shipment_by_id(db, sid)
    if not s: return None
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s

def delete_shipment(db: Session, sid: int):
    s = get_shipment_by_id(db, sid)
    if s:
        db.delete(s)
        db.commit()

def add_comment(db: Session, sid: int, data: schemas.CommentCreate, author="System"):
    c = models.Comment(shipment_id=sid, author=author, text=data.text)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
