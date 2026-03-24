from sqlalchemy.orm import Session
from sqlalchemy import or_
import models, schemas
from datetime import datetime
from collections import defaultdict


def get_shipments(db: Session, search: str = "", status: str = "", mode: str = ""):
    q = db.query(models.Shipment)
    if search:
        s = f"%{search}%"
        q = q.filter(or_(
            models.Shipment.ref.ilike(s),
            models.Shipment.ref2.ilike(s),
            models.Shipment.booking_no.ilike(s),
            models.Shipment.client.ilike(s),
            models.Shipment.quotation_number.ilike(s)
        ))
    if status and status != "All Status":
        q = q.filter(models.Shipment.status.ilike(status))
    if mode and mode != "All Modes":
        q = q.filter(models.Shipment.mode.ilike(mode))
    return q.order_by(models.Shipment.id.desc()).all()


def create_shipment(db: Session, s: schemas.ShipmentCreate):
    allowed = {c.name for c in models.Shipment.__table__.columns}
    data = {k: v for k, v in s.model_dump().items() if k in allowed}
    dbs = models.Shipment(**data)
    db.add(dbs)
    db.commit()
    db.refresh(dbs)
    return dbs


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


# ── EVENTS ──────────────────────────────────────────────────────────────────
def get_events(db: Session, sid: int):
    return db.query(models.ShipmentEvent).filter(models.ShipmentEvent.shipment_id == sid).all()


def add_event(db: Session, sid: int, description: str = "", location: str = "", status: str = ""):
    e = models.ShipmentEvent(
        shipment_id=sid,
        description=description,
        location=location,
        status=status
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def delete_event(db: Session, event_id: int):
    e = db.query(models.ShipmentEvent).filter(models.ShipmentEvent.id == event_id).first()
    if e:
        db.delete(e)
        db.commit()


# ── COMMENTS ────────────────────────────────────────────────────────────────
def get_comments(db: Session, sid: int):
    return db.query(models.ShipmentComment).filter(models.ShipmentComment.shipment_id == sid).all()


def add_comment(db: Session, sid: int, data: schemas.CommentCreate, author: str = "Agent"):
    c = models.ShipmentComment(
        shipment_id=sid,
        author=data.author or author,
        text=data.text
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def delete_comment(db: Session, comment_id: int):
    c = db.query(models.ShipmentComment).filter(models.ShipmentComment.id == comment_id).first()
    if c:
        db.delete(c)
        db.commit()


# ── CONTAINERS ───────────────────────────────────────────────────────────────
def get_containers(db: Session, sid: int):
    return db.query(models.Container).filter(models.Container.shipment_id == sid).all()


def add_container(db: Session, sid: int, data: schemas.ContainerCreate):
    c = models.Container(shipment_id=sid, **data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def update_container(db: Session, cid: int, data: schemas.ContainerCreate):
    c = db.query(models.Container).filter(models.Container.id == cid).first()
    if not c:
        return None
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return c


def delete_container(db: Session, cid: int):
    c = db.query(models.Container).filter(models.Container.id == cid).first()
    if c:
        db.delete(c)
        db.commit()


# ── USERS ────────────────────────────────────────────────────────────────────
def get_users(db: Session):
    return db.query(models.User).all()


def create_user(db: Session, data: schemas.UserCreate):
    from auth import hash_password
    u = models.User(
        email=data.email,
        name=data.name,
        role=data.role,
        hashedpw=hash_password(data.password),
        isactive=True
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def delete_user(db: Session, uid: int):
    u = db.query(models.User).filter(models.User.id == uid).first()
    if u:
        db.delete(u)
        db.commit()


# ── STATS ────────────────────────────────────────────────────────────────────
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
    return {
        "total": total,
        "by_status": by_status,
        "by_mode": by_mode,
        "delayed_count": delayed_count
    }


def get_kpis(db: Session):
    ships = db.query(models.Shipment).all()
    total = len(ships)
    delayed = sum(1 for s in ships if s.status == "Delayed")
    delivered = sum(1 for s in ships if s.status in ("Delivered", "Arrived"))
    delay_rate = f"{round(delayed/total*100)}%" if total else "0%"
    on_time_rate = f"{round(delivered/total*100)}%" if total else "0%"

    transit_days = []
    for s in ships:
        if s.etd and s.eta:
            try:
                d = (datetime.fromisoformat(str(s.eta)) - datetime.fromisoformat(str(s.etd))).days
                if 0 < d < 200:
                    transit_days.append(d)
            except:
                pass
    avg_transit = f"{round(sum(transit_days)/len(transit_days))} days" if transit_days else "N/A"

    by_status, by_carrier, by_client = {}, {}, {}
    for s in ships:
        st = s.status or "Pending"
        by_status[st] = by_status.get(st, 0) + 1
        if s.carrier:
            by_carrier[s.carrier] = by_carrier.get(s.carrier, 0) + 1
        if s.client:
            by_client[s.client] = by_client.get(s.client, 0) + 1

    monthly = defaultdict(int)
    for s in ships:
        if s.created_at:
            try:
                key = datetime.fromisoformat(str(s.created_at)).strftime("%b %Y")
                monthly[key] += 1
            except:
                pass
    monthly_list = [{"month": k, "count": v} for k, v in sorted(monthly.items())][-6:]

    today = datetime.utcnow()
    overdue = []
    for s in ships:
        if s.eta and s.status not in ("Delivered", "Arrived", "Discharged"):
            try:
                days_late = (today - datetime.fromisoformat(str(s.eta))).days
                if days_late > 0:
                    overdue.append({"ref": s.ref, "client": s.client or "", "eta": str(s.eta), "days_late": days_late})
            except:
                pass
    overdue.sort(key=lambda x: x["days_late"], reverse=True)

    return {
        "total": total,
        "on_time_rate": on_time_rate,
        "delay_rate": delay_rate,
        "avg_transit": avg_transit,
        "by_status": by_status,
        "by_carrier": [{"name": k, "count": v} for k, v in sorted(by_carrier.items(), key=lambda x: -x[1])][:5],
        "by_client": [{"name": k, "count": v} for k, v in sorted(by_client.items(), key=lambda x: -x[1])][:5],
        "monthly": monthly_list,
        "overdue": overdue
    }
