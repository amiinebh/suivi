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

def get_kpis(db):
    from datetime import datetime, date
    all_s = db.query(models.Shipment).all()
    if not all_s:
        return {"total":0,"on_time_rate":0,"delay_rate":0,"avg_transit":0,
                "overdue":[],"by_status":{},"by_mode":{},"by_carrier":[],
                "by_client":[],"monthly":[]}

    today = date.today()
    total = len(all_s)
    delayed = [s for s in all_s if s.status == "Delayed"]
    delivered = [s for s in all_s if s.status in ("Delivered","Arrived","Discharged")]

    # On-time: delivered AND eta >= actual (we approximate: status not Delayed)
    on_time = [s for s in delivered if s.status != "Delayed"]
    on_time_rate = round(len(on_time)/total*100,1) if total else 0
    delay_rate   = round(len(delayed)/total*100,1) if total else 0

    # Avg transit time (ETD→ETA in days)
    transit_days = []
    for s in all_s:
        try:
            if s.etd and s.eta:
                etd = datetime.fromisoformat(s.etd.split("T")[0])
                eta = datetime.fromisoformat(s.eta.split("T")[0])
                diff = (eta - etd).days
                if 0 < diff < 200:
                    transit_days.append(diff)
        except: pass
    avg_transit = round(sum(transit_days)/len(transit_days),1) if transit_days else 0

    # Overdue: ETA < today and not delivered
    overdue = []
    for s in all_s:
        try:
            if s.eta and s.status not in ("Delivered","Arrived","Discharged"):
                eta_d = date.fromisoformat(s.eta.split("T")[0])
                if eta_d < today:
                    days_late = (today - eta_d).days
                    overdue.append({"ref":s.ref,"client":s.client,"eta":s.eta,
                                    "days_late":days_late,"status":s.status})
        except: pass
    overdue.sort(key=lambda x: x["days_late"], reverse=True)

    # By status
    by_status = {}
    for s in all_s:
        by_status[s.status] = by_status.get(s.status,0)+1

    # By mode
    by_mode = {}
    for s in all_s:
        by_mode[s.mode] = by_mode.get(s.mode,0)+1

    # By carrier (top 6)
    by_carrier = {}
    for s in all_s:
        if s.carrier:
            by_carrier[s.carrier] = by_carrier.get(s.carrier,0)+1
    by_carrier = sorted([{"name":k,"count":v} for k,v in by_carrier.items()],
                        key=lambda x:x["count"],reverse=True)[:6]

    # By client (top 6)
    by_client = {}
    for s in all_s:
        if s.client:
            by_client[s.client] = by_client.get(s.client,0)+1
    by_client = sorted([{"name":k,"count":v} for k,v in by_client.items()],
                       key=lambda x:x["count"],reverse=True)[:6]

    # Monthly volume (last 6 months)
    from collections import defaultdict
    monthly = defaultdict(int)
    for s in all_s:
        try:
            if s.created_at:
                d = datetime.fromisoformat(s.created_at.split("T")[0])
                key = d.strftime("%b %Y")
                monthly[key] += 1
        except: pass
    # Sort by date
    def month_sort(k):
        try: return datetime.strptime(k, "%b %Y")
        except: return datetime.min
    monthly_sorted = sorted(monthly.items(), key=lambda x: month_sort(x[0]))[-6:]
    monthly_list = [{"month":k,"count":v} for k,v in monthly_sorted]

    return {
        "total": total,
        "on_time_rate": on_time_rate,
        "delay_rate": delay_rate,
        "avg_transit": avg_transit,
        "overdue": overdue[:5],
        "by_status": by_status,
        "by_mode": by_mode,
        "by_carrier": by_carrier,
        "by_client": by_client,
        "monthly": monthly_list,
    }
