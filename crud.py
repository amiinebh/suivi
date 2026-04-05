from sqlalchemy.orm import Session
import models, schemas
from datetime import date, datetime


def get_shipments(db: Session, search: str = "", status: str = "", mode: str = ""):
    q = db.query(models.Shipment)
    if search:
        s = f"%{search}%"
        q = q.filter(
            models.Shipment.ref.ilike(s) |
            models.Shipment.client.ilike(s) |
            models.Shipment.pol.ilike(s) |
            models.Shipment.pod.ilike(s) |
            models.Shipment.carrier.ilike(s) |
            models.Shipment.bookingno.ilike(s)
        )
    if status:
        q = q.filter(models.Shipment.status == status)
    if mode:
        q = q.filter(models.Shipment.mode == mode)
    return q.order_by(models.Shipment.id.desc()).all()


def get_shipment(db: Session, ref: str):
    return db.query(models.Shipment).filter(models.Shipment.ref == ref).first()


def get_shipment_by_id(db: Session, sid: int):
    return db.query(models.Shipment).filter(models.Shipment.id == sid).first()


def create_shipment(db: Session, data: schemas.ShipmentCreate):
    s = models.Shipment(**data.model_dump())
    db.add(s); db.commit(); db.refresh(s)
    return s


def update_shipment(db: Session, sid: int, data: schemas.ShipmentUpdate):
    s = get_shipment_by_id(db, sid)
    if not s:
        return None
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit(); db.refresh(s)
    return s


def delete_shipment(db: Session, sid: int):
    s = get_shipment_by_id(db, sid)
    if s:
        db.delete(s); db.commit()


def add_comment(db: Session, sid: int, data: schemas.CommentCreate):
    c = models.Comment(shipment_id=sid, **data.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return c


def log_email(db: Session, sid: int, subject: str, to: str, sent_by: str):
    e = models.EmailLog(shipment_id=sid, subject=subject, to=to, sent_by=sent_by)
    db.add(e); db.commit()


def get_email_log(db: Session, sid: int):
    return db.query(models.EmailLog).filter(
        models.EmailLog.shipment_id == sid
    ).order_by(models.EmailLog.id.desc()).all()


def get_kpis(db: Session):
    ships = db.query(models.Shipment).all()
    total = len(ships)
    delivered = sum(1 for s in ships if s.status in ("Arrived", "Closed"))
    delayed = 0
    today = date.today()
    for s in ships:
        try:
            if s.eta and s.status not in ("Arrived", "Closed", "Canceled"):
                eta_d = datetime.strptime(str(s.eta).split("T")[0], "%Y-%m-%d").date()
                if eta_d < today:
                    delayed += 1
        except Exception:
            pass
    by_carrier = {}
    for s in ships:
        c = s.carrier or "Unknown"
        by_carrier[c] = by_carrier.get(c, 0) + 1
    top_carrier = sorted(by_carrier.items(), key=lambda x: -x[1])
    return {
        "total": total,
        "delivered": delivered,
        "delayed": delayed,
        "by_carrier": [{"name": k, "count": v} for k, v in top_carrier[:5]],
    }


def _is_export(s):
    try:
        d = (getattr(s, "direction", None) or "").strip().lower()
        if d in ("export", "exp", "x"):
            return True
        if d in ("import", "imp", "m"):
            return False
        ref = (s.ref or "").strip().upper()
        if ref.startswith("ROE"):
            return True
        return False
    except Exception:
        return False


def get_stats(db: Session):
    try:
        ships = db.query(models.Shipment).all()
    except Exception:
        ships = []

    total = len(ships)
    bystatus = {}
    bymode = {}
    export_count = 0
    import_count = 0
    totalteu = 0.0
    delayed = 0
    ocean_count = 0
    road_count = 0
    today = date.today()

    for s in ships:
        try:
            st = (s.status or "Pending").strip() or "Pending"
            bystatus[st] = bystatus.get(st, 0) + 1
        except Exception:
            pass
        try:
            m = (s.mode or "Ocean").strip()
            bymode[m] = bymode.get(m, 0) + 1
            if m.lower() in ("road", "ftl", "truck"):
                road_count += 1
            else:
                ocean_count += 1
        except Exception:
            pass
        try:
            if _is_export(s):
                export_count += 1
            else:
                import_count += 1
        except Exception:
            import_count += 1
        try:
            totalteu += float(s.teu or 0)
        except Exception:
            pass
        try:
            st2 = (s.status or "").strip()
            if s.eta and st2 not in ("Arrived", "Closed", "Canceled"):
                eta_d = datetime.strptime(str(s.eta).split("T")[0], "%Y-%m-%d").date()
                if eta_d < today:
                    delayed += 1
        except Exception:
            pass

    return {
        "total": total,
        "bystatus": bystatus,
        "by_status": bystatus,
        "bymode": bymode,
        "by_mode": bymode,
        "bydirection": {"Export": export_count, "Import": import_count},
        "by_direction": {"Export": export_count, "Import": import_count},
        "export": export_count,
        "import": import_count,
        "totalteu": round(totalteu, 2),
        "total_teu": round(totalteu, 2),
        "delayedcount": delayed,
        "delayed_count": delayed,
        "ocean": ocean_count,
        "road": road_count,
    }
