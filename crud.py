from sqlalchemy.orm import Session
from sqlalchemy import or_
from collections import defaultdict
from datetime import datetime
import models, schemas

def get_shipments(db: Session, search: str = "", status: str = "", mode: str = ""):
    q = db.query(models.Shipment)
    if search:
        s = f"%{search}%"
        q = q.filter(or_(
            models.Shipment.ref.ilike(s),
            models.Shipment.ref2.ilike(s),
            models.Shipment.booking_no.ilike(s),
            models.Shipment.client.ilike(s)
        ))
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
    if not s:
        return None
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
    comment_cls = getattr(models, 'ShipmentComment', None)
    c = comment_cls(shipment_id=sid, author=data.author or author, text=data.text)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c

def get_stats(db: Session):
    ships = db.query(models.Shipment).all()
    total = len(ships)
    by_status = {}
    by_mode = {}
    delayed_count = 0
    for s in ships:
        st = s.status or "Pending"
        by_status[st] = by_status.get(st, 0) + 1
        md = s.mode or "Ocean"
        by_mode[md] = by_mode.get(md, 0) + 1
        if st == "Delayed":
            delayed_count += 1
    return {"total": total, "by_status": by_status, "by_mode": by_mode, "delayed_count": delayed_count}

def get_kpis(db: Session):
    ships = db.query(models.Shipment).all()
    total = len(ships)
    delayed = sum(1 for s in ships if (s.status or "") == "Delayed")
    delivered = sum(1 for s in ships if (s.status or "") in ("Delivered", "Arrived"))
    on_time_rate = f"{round(delivered/total*100)}%" if total else "0%"
    delay_rate = f"{round(delayed/total*100)}%" if total else "0%"
    transit_days = []
    by_status = {}
    by_carrier = {}
    by_client = {}
    monthly = defaultdict(int)
    overdue = []
    today = datetime.utcnow()
    for s in ships:
        st = s.status or "Pending"
        by_status[st] = by_status.get(st, 0) + 1
        if s.carrier:
            by_carrier[s.carrier] = by_carrier.get(s.carrier, 0) + 1
        if s.client:
            by_client[s.client] = by_client.get(s.client, 0) + 1
        if s.created_at:
            try:
                dt = datetime.fromisoformat(str(s.created_at))
                monthly[dt.strftime("%b %Y")] += 1
            except Exception:
                pass
        if s.etd and s.eta:
            try:
                etd = datetime.fromisoformat(str(s.etd))
                eta = datetime.fromisoformat(str(s.eta))
                d = (eta - etd).days
                if 0 < d < 200:
                    transit_days.append(d)
            except Exception:
                pass
        if s.eta and st not in ("Delivered", "Arrived", "Discharged"):
            try:
                eta = datetime.fromisoformat(str(s.eta))
                days_late = (today - eta).days
                if days_late > 0:
                    overdue.append({"ref": s.ref, "client": s.client or "", "eta": str(s.eta), "days_late": days_late})
            except Exception:
                pass
    overdue.sort(key=lambda x: x['days_late'], reverse=True)
    avg_transit = f"{round(sum(transit_days)/len(transit_days))} days" if transit_days else "N/A"
    monthly_list = [{"month": k, "count": v} for k, v in sorted(monthly.items())][-6:]
    by_carrier_list = [{"name": k, "count": v} for k, v in sorted(by_carrier.items(), key=lambda x: -x[1])][:5]
    by_client_list = [{"name": k, "count": v} for k, v in sorted(by_client.items(), key=lambda x: -x[1])][:5]
    return {"total": total, "on_time_rate": on_time_rate, "delay_rate": delay_rate, "avg_transit": avg_transit, "by_status": by_status, "by_carrier": by_carrier_list, "by_client": by_client_list, "monthly": monthly_list, "overdue": overdue}
