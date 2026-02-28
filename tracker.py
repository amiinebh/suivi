import requests, os, time, logging
from datetime import datetime
from sqlalchemy.orm import Session
import models, crud

logger = logging.getLogger("tracker")
logging.basicConfig(level=logging.INFO)

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN") or os.getenv("SHIPSGO_API_KEY","")
BASE  = "https://api.shipsgo.com/v2"
OCEAN = f"{BASE}/ocean/shipments"
AIR   = f"{BASE}/air/shipments"

SCAC_MAP = {
    "CMAU":"CMDU","CGMU":"CMDU","SEKU":"CMDU","FSCU":"CMDU","GESU":"CMDU",
    "TCNU":"CMDU","TLLU":"CMDU","CSFU":"CMDU","ECMU":"CMDU","SMUU":"CMDU",
    "APHU":"APLU","APLU":"APLU",
    "HLCU":"HLCU","HLXU":"HLCU",
    "MAEU":"MAEU","MSKU":"MAEU","MCPU":"MAEU","MRKU":"MAEU",
    "MSCU":"MSCU","MEDU":"MSCU","MSDU":"MSCU","BMOU":"MSCU",
    "EISU":"EISU","EMCU":"EISU","EGHU":"EISU",
    "CCLU":"COSU","CBHU":"COSU","COSU":"COSU",
    "ONEY":"ONEY","NYKU":"ONEY",
    "YMLU":"YMLU","YMTU":"YMLU",
    "HMMU":"HDMU","HDMU":"HDMU",
    "ZIMU":"ZIMU","ZCSU":"ZIMU",
    "PILU":"PILU",
}

# Map Shipsgo statuses → our internal statuses
STATUS_MAP = {
    "Sailing":    ["sailing","inprogress","in_progress","in transit","on board","loaded",
                   "departed","at sea","enroute","en_route"],
    "Arrived":    ["arrived","discharged","gate_out","gate out","completed","final",
                   "delivered","unloaded"],
    "Delayed":    ["rollover","delayed","rolled","late"],
    "Discharged": ["discharged","unloaded","available"],
    "Pending":    ["pending","booking","not departed","awaiting","created","registered",
                   "booked","inprogress"],  # fallback
}

def headers():
    return {"X-Shipsgo-User-Token": SHIPSGO_TOKEN,
            "Content-Type": "application/json", "Accept": "application/json"}

def scac(no): return SCAC_MAP.get((no or "")[:4].upper(), "")

def map_status(raw):
    if not raw: return None
    r = raw.lower().replace("-","_").replace(" ","_")
    # Direct exact matches first
    exact = {
        "inprogress": "Sailing", "in_progress": "Sailing", "sailing": "Sailing",
        "enroute": "Sailing", "en_route": "Sailing",
        "discharged": "Discharged", "arrived": "Arrived",
        "delivered": "Delivered", "completed": "Delivered",
        "delayed": "Delayed", "rollover": "Delayed",
        "pending": "Pending", "created": "Pending", "booked": "Pending",
        "registered": "Pending", "untracked": "Pending",
    }
    if r in exact: return exact[r]
    for st, keys in STATUS_MAP.items():
        if any(k in r for k in keys): return st
    return None

def parse_date(v):
    if not v: return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ","%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M","%Y-%m-%d"):
        try: return datetime.strptime(s[:26], fmt).strftime("%Y-%m-%d")
        except: pass
    return s[:10] if len(s) >= 10 else None

def track_ocean(db: Session, shipment):
    no = (shipment.ref2 or "").strip()
    if not no:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}

    if not SHIPSGO_TOKEN:
        return {"ref": shipment.ref, "status": "error", "reason": "SHIPSGO_TOKEN not set in Railway env vars"}

    body = {"container_number": no}
    sc = scac(no)
    if sc: body["carrier"] = sc
    if shipment.booking_no: body["booking_number"] = shipment.booking_no
    if shipment.ref:        body["reference"] = shipment.ref

    shipsgo_id = shipment.shipsgo_id

    if not shipsgo_id:
        logger.info(f"[{shipment.ref}] Creating Shipsgo shipment for {no}")
        r = requests.post(OCEAN, headers=headers(), json=body, timeout=20)
        logger.info(f"[{shipment.ref}] POST response: {r.status_code} {r.text[:300]}")
        if r.status_code in (200, 201, 409):
            d = r.json()
            shipsgo_id = (d.get("shipment") or {}).get("id")
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:300]}"}
        time.sleep(2)

    if not shipsgo_id:
        return {"ref": shipment.ref, "status": "error", "reason": "Could not get shipsgo_id"}

    # Save shipsgo_id immediately
    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
    if not obj.shipsgo_id:
        obj.shipsgo_id = shipsgo_id
        db.commit()

    r2 = requests.get(f"{OCEAN}/{shipsgo_id}", headers=headers(), timeout=20)
    logger.info(f"[{shipment.ref}] GET response: {r2.status_code} {r2.text[:500]}")
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:300]}"}

    data  = r2.json()
    ship  = data.get("shipment") or {}
    route = ship.get("route") or {}
    pod_d = route.get("port_of_discharge") or {}
    pol_d = route.get("port_of_loading") or {}

    # ETA: try date_of_discharge, fallback to initial
    new_eta = (parse_date(pod_d.get("date_of_discharge")) or
               parse_date(pod_d.get("date_of_discharge_initial")))
    new_etd = (parse_date(pol_d.get("date_of_loading")) or
               parse_date(pol_d.get("date_of_loading_initial")))

    raw_status = ship.get("status","")
    new_status = map_status(str(raw_status))

    new_pol = ((pol_d.get("location") or {}).get("name") or "")
    new_pod = ((pod_d.get("location") or {}).get("name") or "")

    # Extract vessel from containers
    containers = ship.get("containers") or []
    new_vessel = ""
    for c in containers:
        v = c.get("vessel") or {}
        if isinstance(v, dict) and v.get("name"):
            new_vessel = v["name"]; break

    # Carrier
    carrier_info = ship.get("carrier") or {}
    new_carrier = carrier_info.get("name","") if isinstance(carrier_info, dict) else ""

    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}→{new_status}")
        crud.add_event(db, obj.id, "", f"Status: {old} → {new_status}", new_status)
    if new_vessel and new_vessel != obj.vessel:
        obj.vessel = new_vessel; changed.append(f"vessel→{new_vessel}")
    if new_eta:
        old_eta = obj.eta; obj.eta = new_eta
        if old_eta != new_eta: changed.append(f"ETA {old_eta}→{new_eta}")
    if new_etd: obj.etd = new_etd
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    if new_carrier and not obj.carrier: obj.carrier = new_carrier
    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()

    logger.info(f"[{shipment.ref}] Done. changed={changed} eta={new_eta} status={new_status}")
    return {"ref": shipment.ref, "shipsgo_id": shipsgo_id,
            "status": "updated" if changed else "no_change",
            "changed": changed, "raw_status": raw_status,
            "eta": new_eta, "vessel": new_vessel}

def track_air(db: Session, shipment):
    awb = (shipment.ref2 or "").strip()
    if not awb: return {"ref": shipment.ref, "status": "skipped", "reason": "No AWB"}
    if not SHIPSGO_TOKEN:
        return {"ref": shipment.ref, "status": "error", "reason": "SHIPSGO_TOKEN not set"}

    body = {"awb_number": awb}
    if shipment.ref: body["reference"] = shipment.ref

    shipsgo_id = shipment.shipsgo_id
    if not shipsgo_id:
        r = requests.post(AIR, headers=headers(), json=body, timeout=20)
        logger.info(f"[AIR {shipment.ref}] POST: {r.status_code} {r.text[:300]}")
        if r.status_code in (200, 201, 409):
            shipsgo_id = (r.json().get("shipment") or {}).get("id")
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:300]}"}
        time.sleep(2)

    if not shipsgo_id:
        return {"ref": shipment.ref, "status": "error", "reason": "No shipsgo_id"}

    r2 = requests.get(f"{AIR}/{shipsgo_id}", headers=headers(), timeout=20)
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:300]}"}

    data  = r2.json()
    ship  = data.get("shipment") or {}
    route = ship.get("route") or {}
    dest  = route.get("destination") or {}
    orig  = route.get("origin") or {}

    new_eta    = parse_date(dest.get("date_of_rcf"))
    new_etd    = parse_date(orig.get("date_of_dep"))
    raw_status = ship.get("status","")
    new_status = map_status(str(raw_status))
    carrier    = ((ship.get("airline") or {}).get("name") or "")
    new_pod    = ((dest.get("location") or {}).get("name") or "")
    new_pol    = ((orig.get("location") or {}).get("name") or "")

    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}→{new_status}")
        crud.add_event(db, obj.id, "", f"Status: {old} → {new_status}", new_status)
    if new_eta:
        obj.eta = new_eta; changed.append(f"ETA→{new_eta}")
    if new_etd: obj.etd = new_etd
    if carrier and not obj.carrier: obj.carrier = carrier
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    if shipsgo_id and not obj.shipsgo_id: obj.shipsgo_id = shipsgo_id
    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()
    return {"ref": shipment.ref, "shipsgo_id": shipsgo_id,
            "status": "updated" if changed else "no_change", "changed": changed}

def track_and_update(db: Session, shipment):
    return track_air(db, shipment) if shipment.mode == "Air" else track_ocean(db, shipment)

def run_auto_tracking(db: Session):
    active = db.query(models.Shipment).filter(
        models.Shipment.status.notin_(["Delivered"]),
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    return [track_and_update(db, s) for s in active]

def get_geojson(shipment, db: Session):
    sid = shipment.shipsgo_id
    if not sid: return None
    base = OCEAN if shipment.mode != "Air" else AIR
    r = requests.get(f"{base}/{sid}/geojson", headers=headers(), timeout=20)
    if r.status_code == 200: return r.json().get("geojson")
    return None
