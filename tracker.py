import requests, os, time
from datetime import datetime
from sqlalchemy.orm import Session
import models, crud

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN", "f12e82f3-16c7-4d90-bae4-e63a3aee9c3a")
BASE   = "https://api.shipsgo.com/v2"
OCEAN  = f"{BASE}/ocean/shipments"
AIR    = f"{BASE}/air/shipments"

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
STATUS_MAP = {
    "In Transit": ["sailing","in_transit","inprogress","in transit","on board","loaded","departed","at sea"],
    "Delivered":  ["delivered","discharged","gate_out","gate out","completed","final"],
    "Customs":    ["customs","inspection"],
    "Delayed":    ["rollover","delayed","rolled"],
    "Pending":    ["pending","booking","not departed","awaiting","created"],
}

def headers():
    return {"X-Shipsgo-User-Token": SHIPSGO_TOKEN,
            "Content-Type": "application/json", "Accept": "application/json"}

def scac(no): return SCAC_MAP.get((no or "")[:4].upper(), "")

def map_status(raw):
    if not raw: return None
    r = raw.lower().replace("-","_")
    for st, keys in STATUS_MAP.items():
        if any(k in r for k in keys): return st
    return None

def parse_date(v):
    if not v: return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M","%Y-%m-%d"):
        try: return datetime.strptime(s[:19], fmt).strftime("%Y-%m-%d")
        except: pass
    return s[:10] if len(s) >= 10 else None

def track_ocean(db: Session, shipment):
    no = (shipment.ref2 or "").strip()
    if not no: return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}

    body = {"container_number": no}
    sc = scac(no)
    if sc: body["carrier"] = sc
    if shipment.booking_no: body["booking_number"] = shipment.booking_no
    if shipment.ref: body["reference"] = shipment.ref

    shipsgo_id = shipment.shipsgo_id
    if not shipsgo_id:
        r = requests.post(OCEAN, headers=headers(), json=body, timeout=20)
        if r.status_code in (200, 201, 409):
            d = r.json()
            shipsgo_id = d.get("shipment", {}).get("id")
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:200]}"}
        time.sleep(2)

    if not shipsgo_id:
        return {"ref": shipment.ref, "status": "error", "reason": "No shipsgo_id"}

    r2 = requests.get(f"{OCEAN}/{shipsgo_id}", headers=headers(), timeout=20)
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:200]}"}

    data  = r2.json()
    ship  = data.get("shipment", {})
    route = ship.get("route") or {}
    pod_d = route.get("port_of_discharge") or {}
    pol_d = route.get("port_of_loading") or {}

    new_eta    = parse_date(pod_d.get("date_of_discharge"))
    new_etd    = parse_date(pol_d.get("date_of_loading"))
    raw_status = ship.get("status","")
    new_status = map_status(str(raw_status))
    new_pol    = (pol_d.get("location") or {}).get("name","") or ""
    new_pod    = (pod_d.get("location") or {}).get("name","") or ""

    containers = ship.get("containers",[])
    new_vessel = ""
    events_raw = []
    for c in containers:
        v = c.get("vessel",{})
        if isinstance(v, dict) and v.get("name"): new_vessel = v["name"]
        for mv in (c.get("movements") or []):
            events_raw.append(mv)

    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}→{new_status}")
        crud.add_event(db, obj.id, "", f"Status changed: {old} → {new_status}", new_status)
    if new_vessel and new_vessel != obj.vessel:
        obj.vessel = new_vessel; changed.append(f"vessel→{new_vessel}")
    if new_eta and new_eta != obj.eta:
        old = obj.eta; obj.eta = new_eta; changed.append(f"ETA {old}→{new_eta}")
    if new_etd and new_etd != obj.etd:
        obj.etd = new_etd
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    if shipsgo_id and not obj.shipsgo_id: obj.shipsgo_id = shipsgo_id

    # Save events/movements
    existing_descs = {e.description for e in obj.events}
    carrier_info = ship.get("carrier",{})
    new_carrier = carrier_info.get("name","") if isinstance(carrier_info, dict) else ""
    if new_carrier and not obj.carrier: obj.carrier = new_carrier

    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()

    return {"ref": shipment.ref, "shipsgo_id": shipsgo_id, "status": "updated" if changed else "no_change",
            "changed": changed, "raw_status": raw_status, "eta": new_eta, "vessel": new_vessel}

def track_air(db: Session, shipment):
    awb = (shipment.ref2 or "").strip()
    if not awb: return {"ref": shipment.ref, "status": "skipped", "reason": "No AWB"}

    body = {"awb_number": awb}
    if shipment.ref: body["reference"] = shipment.ref

    shipsgo_id = shipment.shipsgo_id
    if not shipsgo_id:
        r = requests.post(AIR, headers=headers(), json=body, timeout=20)
        if r.status_code in (200, 201, 409):
            shipsgo_id = r.json().get("shipment", {}).get("id")
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:200]}"}
        time.sleep(2)

    if not shipsgo_id:
        return {"ref": shipment.ref, "status": "error", "reason": "No shipsgo_id"}

    r2 = requests.get(f"{AIR}/{shipsgo_id}", headers=headers(), timeout=20)
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:200]}"}

    data  = r2.json()
    ship  = data.get("shipment", {})
    route = ship.get("route") or {}
    dest  = route.get("destination") or {}
    orig  = route.get("origin") or {}
    new_eta    = parse_date(dest.get("date_of_rcf"))
    new_etd    = parse_date(orig.get("date_of_dep"))
    raw_status = ship.get("status","")
    new_status = map_status(str(raw_status))
    carrier    = (ship.get("airline") or {}).get("name","")
    new_pod    = ((dest.get("location") or {}).get("name") or "")
    new_pol    = ((orig.get("location") or {}).get("name") or "")

    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}→{new_status}")
        crud.add_event(db, obj.id, "", f"Status changed: {old} → {new_status}", new_status)
    if new_eta and new_eta != obj.eta:
        obj.eta = new_eta; changed.append(f"ETA→{new_eta}")
    if new_etd and new_etd != obj.etd: obj.etd = new_etd
    if carrier and not obj.carrier: obj.carrier = carrier
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    if shipsgo_id and not obj.shipsgo_id: obj.shipsgo_id = shipsgo_id

    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()
    return {"ref": shipment.ref, "shipsgo_id": shipsgo_id,
            "status": "updated" if changed else "no_change", "changed": changed}

def track_and_update(db: Session, shipment):
    if shipment.mode == "Air":
        return track_air(db, shipment)
    return track_ocean(db, shipment)

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
