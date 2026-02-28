from sqlalchemy.orm import Session
import models, schemas

def get_user_by_username(db, u): return db.query(models.User).filter(models.User.username==u).first()
def get_all_users(db): return db.query(models.User).all()
def create_user(db, user: schemas.UserCreate, hashed_password: str):
    u = models.User(username=user.username, full_name=user.full_name,
                    email=user.email, hashed_password=hashed_password, role=user.role)
    db.add(u); db.commit(); db.refresh(u); return u

def get_all_shipments(db): return db.query(models.Shipment).order_by(models.Shipment.id.desc()).all()
def get_shipment(db, id): return db.query(models.Shipment).filter(models.Shipment.id==id).first()
def get_shipment_by_ref(db, ref): return db.query(models.Shipment).filter(models.Shipment.ref==ref).first()

def create_shipment(db, s: schemas.ShipmentCreate, user_id: int):
    obj = models.Shipment(**s.model_dump(), created_by=user_id)
    db.add(obj); db.commit(); db.refresh(obj); return obj

def update_shipment(db, id, s: schemas.ShipmentCreate):
    obj = get_shipment(db, id)
    if not obj: return None
    for k, v in s.model_dump().items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj); return obj

def delete_shipment(db, id):
    obj = get_shipment(db, id)
    if not obj: return False
    db.delete(obj); db.commit(); return True

def get_stats(db):
    all_s = db.query(models.Shipment).all()
    return {"total": len(all_s),
            "in_transit": sum(1 for s in all_s if s.status=="In Transit"),
            "delivered":  sum(1 for s in all_s if s.status=="Delivered"),
            "issues":     sum(1 for s in all_s if s.status in ("Delayed","Customs")),
            "ocean":      sum(1 for s in all_s if s.mode=="Ocean"),
            "road":       sum(1 for s in all_s if s.mode=="Road"),
            "air":        sum(1 for s in all_s if s.mode=="Air")}
