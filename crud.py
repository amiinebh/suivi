from sqlalchemy.orm import Session
from sqlalchemy import or_
import models, schemas

def get_shipments(db:Session, search:str="", status:str="", mode:str=""):
    q=db.query(models.Shipment)
    if search:
        s=f"%{search}%"
        q=q.filter(or_(models.Shipment.ref.ilike(s),models.Shipment.ref2.ilike(s),
            models.Shipment.booking_no.ilike(s),models.Shipment.client.ilike(s),
            models.Shipment.pol.ilike(s),models.Shipment.pod.ilike(s)))
    if status and status not in ("","All Status"): q=q.filter(models.Shipment.status.ilike(status))
    if mode and mode not in ("","All Modes"): q=q.filter(models.Shipment.mode.ilike(mode))
    return q.order_by(models.Shipment.id.desc()).all()

def create_shipment(db:Session, s:schemas.ShipmentCreate):
    allowed={c.name for c in models.Shipment.__table__.columns}
    data={k:v for k,v in s.model_dump().items() if k in allowed}
    obj=models.Shipment(**data); db.add(obj); db.commit(); db.refresh(obj); return obj

def get_shipment(db:Session, ref:str):
    return db.query(models.Shipment).filter(models.Shipment.ref==ref).first()

def get_shipment_by_id(db:Session, sid:int):
    return db.query(models.Shipment).filter(models.Shipment.id==sid).first()

def update_shipment(db:Session, sid:int, data:schemas.ShipmentUpdate):
    s=get_shipment_by_id(db,sid)
    if not s: return None
    allowed={c.name for c in models.Shipment.__table__.columns}
    for k,v in data.model_dump(exclude_unset=True).items():
        if k in allowed: setattr(s,k,v)
    db.commit(); db.refresh(s); return s

def delete_shipment(db:Session, sid:int):
    s=get_shipment_by_id(db,sid)
    if s: db.delete(s); db.commit()

def add_comment(db:Session, sid:int, data:schemas.CommentCreate, author="System"):
    c=models.ShipmentComment(shipment_id=sid,author=author,text=data.text)
    db.add(c); db.commit(); db.refresh(c); return c

def add_container(db:Session, sid:int, data:schemas.ContainerCreate):
    c=models.Container(shipment_id=sid,**data.model_dump())
    db.add(c); db.commit(); db.refresh(c); return c

def get_stats(db:Session):
    ships=db.query(models.Shipment).all()
    by_status,by_mode={},{}
    for s in ships:
        st=s.status or "Pending"; by_status[st]=by_status.get(st,0)+1
        md=s.mode or "Ocean"; by_mode[md]=by_mode.get(md,0)+1
    return {"total":len(ships),"by_status":by_status,"by_mode":by_mode,
            "delayed_count":by_status.get("Delayed",0)}

def get_kpis(db:Session):
    from datetime import datetime
    from collections import defaultdict
    ships=db.query(models.Shipment).all()
    total=len(ships)
    delayed=sum(1 for s in ships if s.status=="Delayed")
    delivered=sum(1 for s in ships if s.status in ("Delivered","Arrived","Discharged"))
    active=sum(1 for s in ships if s.status in ("Sailing","In Transit","Loading","On Board"))
    pending=sum(1 for s in ships if s.status in ("Pending","Booked","Confirmed"))
    delay_rate=f"{round(delayed/total*100)}%" if total else "0%"
    on_time_rate=f"{round(delivered/total*100)}%" if total else "0%"
    transit_days=[]
    for s in ships:
        if s.etd and s.eta:
            try:
                d=(datetime.fromisoformat(str(s.eta))-datetime.fromisoformat(str(s.etd))).days
                if 0<d<200: transit_days.append(d)
            except: pass
    avg_transit=f"{round(sum(transit_days)/len(transit_days))} days" if transit_days else "N/A"
    by_status,by_carrier,by_client,by_mode,by_dir,by_pol,by_pod={},{},{},{},{},{},{}
    for s in ships:
        st=s.status or "Pending"; by_status[st]=by_status.get(st,0)+1
        md=s.mode or "Ocean"; by_mode[md]=by_mode.get(md,0)+1
        if s.carrier: by_carrier[s.carrier]=by_carrier.get(s.carrier,0)+1
        if s.client:  by_client[s.client]=by_client.get(s.client,0)+1
        if s.direction: by_dir[s.direction]=by_dir.get(s.direction,0)+1
        if s.pol: by_pol[s.pol]=by_pol.get(s.pol,0)+1
        if s.pod: by_pod[s.pod]=by_pod.get(s.pod,0)+1
    monthly=defaultdict(int)
    for s in ships:
        if s.created_at:
            try: monthly[datetime.fromisoformat(str(s.created_at)).strftime("%b %Y")]+=1
            except: pass
    today=datetime.utcnow()
    overdue=[]
    for s in ships:
        if s.eta and s.status not in ("Delivered","Arrived","Discharged"):
            try:
                dl=(today-datetime.fromisoformat(str(s.eta))).days
                if dl>0: overdue.append({"ref":s.ref,"client":s.client or "","carrier":s.carrier or "","pol":s.pol or "","pod":s.pod or "","eta":str(s.eta),"days_late":dl})
            except: pass
    overdue.sort(key=lambda x:x["days_late"],reverse=True)
    return {
        "total":total,"delayed":delayed,"delivered":delivered,"active":active,"pending":pending,
        "on_time_rate":on_time_rate,"delay_rate":delay_rate,"avg_transit":avg_transit,
        "by_status":by_status,
        "by_mode":[{"name":k,"count":v} for k,v in by_mode.items()],
        "by_direction":[{"name":k,"count":v} for k,v in by_dir.items()],
        "by_carrier":sorted([{"name":k,"count":v} for k,v in by_carrier.items()],key=lambda x:-x["count"])[:8],
        "by_client":sorted([{"name":k,"count":v} for k,v in by_client.items()],key=lambda x:-x["count"])[:8],
        "top_pols":sorted([{"name":k,"count":v} for k,v in by_pol.items()],key=lambda x:-x["count"])[:5],
        "top_pods":sorted([{"name":k,"count":v} for k,v in by_pod.items()],key=lambda x:-x["count"])[:5],
        "monthly":[{"month":k,"count":v} for k,v in sorted(monthly.items())][-12:],
        "overdue":overdue[:10],
    }
