import requests, os
from datetime import datetime
from sqlalchemy.orm import Session
import crud, models

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN", "3fd0583a-9281-4c30-8d9d-ececa0fff69c")
SHIPSGO_URL   = "https://shipsgo.com/api/v1.2/ContainerService/GetContainerInfo"

STATUS_MAP = {
    "In Transit": ["in transit","vessel departure","departed","on board","loaded","sailing","at sea"],
    "Delivered":  ["delivered","final delivery","gate out","picked up","completed"],
    "Customs":    ["customs","customs hold","import customs","export customs","inspection"],
    "Delayed":    ["rollover","delayed","missed connection","vessel change","rolled over"],
    "Pending":    ["pending","booking","confirmed","not departed","pre-departure"],
}

def map_status(raw):
    if not raw: return None
    r = raw.lower()
    for status, keywords in STATUS_MAP.items():
        if any(k in r for k in keywords): return status
    return None

def track_and_update(db: Session, shipment) -> dict:
    container_no = (shipment.ref2 or "").strip()
    if not container_no:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}
    try:
        response = requests.get(SHIPSGO_URL, params={
            "authorizationCode": SHIPSGO_TOKEN,
            "containerNo": container_no,
            "shippingLineCode": "AUTO"
        }, timeout=15)
        if response.status_code != 200:
            return {"ref": shipment.ref, "status": "error", "reason": f"HTTP {response.status_code}"}
        data = response.json()
        raw_status = data.get("containerStatus") or data.get("status") or ""
        vessel     = data.get("vesselName") or data.get("vessel") or ""
        eta_raw    = data.get("eta") or data.get("estimatedArrival") or ""
        new_eta = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try: new_eta = datetime.strptime(eta_raw[:10], fmt[:len(eta_raw[:10])]).strftime("%Y-%m-%d"); break
            except: pass
        new_status = map_status(raw_status)
        changed = []
        db_s = crud.get_shipment(db, shipment.id)
        if new_status and new_status != db_s.status: db_s.status = new_status; changed.append(f"status → {new_status}")
        if vessel and vessel != db_s.vessel: db_s.vessel = vessel; changed.append(f"vessel → {vessel}")
        if new_eta and new_eta != db_s.eta: db_s.eta = new_eta; changed.append(f"eta → {new_eta}")
        db_s.last_tracked = datetime.utcnow().isoformat()
        db.commit()
        return {"ref": shipment.ref, "container": container_no, "raw_status": raw_status,
                "new_status": new_status, "vessel": vessel, "eta": new_eta,
                "changed": changed, "status": "updated" if changed else "no_change"}
    except requests.exceptions.Timeout:
        return {"ref": shipment.ref, "status": "error", "reason": "Timeout"}
    except Exception as e:
        return {"ref": shipment.ref, "status": "error", "reason": str(e)}

def run_auto_tracking(db: Session) -> list:
    active = db.query(models.Shipment).filter(
        models.Shipment.mode == "Ocean",
        models.Shipment.status.notin_(["Delivered"]),
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    return [track_and_update(db, s) for s in active]
