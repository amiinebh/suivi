import os, logging, requests
from datetime import datetime
from sqlalchemy.orm import Session
import models, crud

logger = logging.getLogger("tracker")
logging.basicConfig(level=logging.INFO)

PREFIX_TO_SCAC = {
    "CMAU":"CMDU","CGMU":"CMDU","SEKU":"CMDU","FSCU":"CMDU","GESU":"CMDU",
    "TCNU":"CMDU","TLLU":"CMDU","CSFU":"CMDU","ECMU":"CMDU","SMUU":"CMDU",
    "APHU":"CMDU","CMNU":"CMDU","LYKU":"CMDU",
    "MSCU":"MSCU","MEDU":"MSCU","MSDU":"MSCU","BMOU":"MSCU","MSOU":"MSCU",
    "MAEU":"MAEU","MSKU":"MAEU","MCPU":"MAEU","MRKU":"MAEU",
    "HLCU":"HLCU","HLXU":"HLCU","UASU":"HLCU",
    "EISU":"EISU","EMCU":"EISU","EGHU":"EISU","EVGU":"EISU","TRIU":"EISU","TCKU":"EISU",
    "CCLU":"COSU","CBHU":"COSU","COSU":"COSU","COCU":"COSU","CSNU":"COSU",
    "ONEY":"ONEY","NYKU":"ONEY","MOLU":"ONEY","KMTU":"ONEY","TEXU":"ONEY",
    "YMLU":"YMLU","YMTU":"YMLU",
    "HMMU":"HDMU","HDMU":"HDMU",
    "ZIMU":"ZIMU","ZCSU":"ZIMU",
    "PILU":"PILU","PCLU":"PILU",
    "APZU":"APLU","APLU":"APLU",
    "WHLU":"WHLC",
    "OOLU":"OOLU","OOCU":"OOLU",
    "SUDU":"SUDU","LGBU":"SUDU",
}
CARRIER_NAME_TO_SCAC = {
    "cma":"CMDU","cma cgm":"CMDU","cmacgm":"CMDU","cma-cgm":"CMDU",
    "msc":"MSCU","mediterranean shipping":"MSCU",
    "maersk":"MAEU","maersk line":"MAEU",
    "hapag":"HLCU","hapag-lloyd":"HLCU","hapag lloyd":"HLCU",
    "evergreen":"EISU","cosco":"COSU","one":"ONEY",
    "yang ming":"YMLU","hmm":"HDMU","zim":"ZIMU",
    "pil":"PILU","apl":"APLU","wan hai":"WHLC","oocl":"OOLU",
    "hamburg sud":"SUDU",
}

def resolve_scac(container_no, carrier_input):
    if carrier_input:
        key = carrier_input.lower().strip()
        if key in CARRIER_NAME_TO_SCAC: return CARRIER_NAME_TO_SCAC[key]
        if len(carrier_input) == 4 and carrier_input.isalpha(): return carrier_input.upper()
        for name, scac in CARRIER_NAME_TO_SCAC.items():
            if key in name or name in key: return scac
    return PREFIX_TO_SCAC.get((container_no or "")[:4].upper(), "")

def parse_date(v):
    if not v: return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ","%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M",
                "%Y-%m-%d %H:%M:%S","%Y-%m-%d"):
        try: return datetime.strptime(s[:19].replace("Z",""), fmt[:19]).strftime("%Y-%m-%d")
        except: pass
    return s[:10] if len(s) >= 10 else None

STATUS_KEYWORDS = [
    ("DELIVERED","Delivered"),("GATE OUT","Delivered"),("EMPTY RETURNED","Delivered"),
    ("VESSEL DEPARTED","Sailing"),("LOADED ON VESSEL","Sailing"),("DEPARTED","Sailing"),
    ("SAILING","Sailing"),("EN ROUTE","Sailing"),("IN TRANSIT","Sailing"),
    ("VESSEL ARRIVED","Arrived"),("ARRIVED","Arrived"),
    ("DISCHARGED","Discharged"),("UNLOADED","Discharged"),
    ("GATE IN","Pending"),("RECEIVED","Pending"),("BOOKING","Pending"),
]

def map_status(movement):
    if not movement: return None
    upper = (movement or "").upper()
    for kw, st in STATUS_KEYWORDS:
        if kw in upper: return st
    return None

# ─── CMA CGM direct tracker ────────────────────────────────────────────────
def track_cmacgm(container):
    """Call CMA CGM public tracking API — no auth required."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.cma-cgm.com/",
        "Origin": "https://www.cma-cgm.com",
    }
    url = f"https://www.cma-cgm.com/ebusiness/tracking/search?SearchBy=Container&Reference={container}&search=Search"
    r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
    logger.info(f"[CMACGM] {r.status_code} len={len(r.text)}")
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        data = r.json()
        return data, None
    except:
        # Try extracting JSON from HTML response
        import re
        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.+?});', r.text, re.DOTALL)
        if m:
            import json
            try: return json.loads(m.group(1)), None
            except: pass
        return None, "Could not parse response"

# ─── MSC direct tracker ────────────────────────────────────────────────────
def track_msc(container):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = "https://www.msc.com/api/feature/tools/TrackingInfo"
    body = {"Identifier": container, "IdentifierType": "Container",
            "IsEmptySearch": False, "ShipmentType": "Container"}
    r = requests.post(url, json=body, headers=headers, timeout=25)
    logger.info(f"[MSC] {r.status_code}")
    if r.status_code != 200: return None, f"HTTP {r.status_code}"
    try: return r.json(), None
    except: return None, "Bad JSON"

# ─── Maersk direct tracker ─────────────────────────────────────────────────
def track_maersk(container):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Consumer-Key": "TLFbdKfJeQksTbGnkZYiMn8H4GjEYkdp",  # Maersk public portal key
    }
    url = f"https://api.maersk.com/track/shipments?containerNumber={container}"
    r = requests.get(url, headers=headers, timeout=25)
    logger.info(f"[MAERSK] {r.status_code}")
    if r.status_code != 200: return None, f"HTTP {r.status_code}"
    try: return r.json(), None
    except: return None, "Bad JSON"

# ─── Generic fallback: Shipsgo if token available ──────────────────────────
def track_shipsgo(container, scac):
    token = os.getenv("SHIPSGO_TOKEN","") or os.getenv("SHIPSGO_API_KEY","")
    if not token: return None, "No SHIPSGO_TOKEN"
    url = "https://shipsgo.com/api/v1.2/ContainerService/PostContainerInfo"
    body = {"authCode": token, "containerNo": container,
            "shippingLine": scac, "referenceNo": container}
    r = requests.post(url, json=body, timeout=25)
    if r.status_code != 200: return None, f"HTTP {r.status_code}"
    try:
        d = r.json()
        if d.get("message") == "NOT_ENOUGH_CREDITS": return None, "No credits"
        return d, None
    except: return None, "Bad JSON"

def extract_events_generic(data):
    """Try to extract events list from various JSON structures."""
    if not data: return []
    # Try common keys
    for key in ("events","movements","trackingDetails","containers","result",
                "trackResults","data","shipmentInfo"):
        val = data.get(key) if isinstance(data, dict) else None
        if isinstance(val, list) and val: return val
        if isinstance(val, dict):
            for k2 in ("events","movements","containers","details"):
                v2 = val.get(k2)
                if isinstance(v2, list) and v2: return v2
    return []

def parse_events(events):
    """Parse events list → (status, eta, vessel, pol, pod, latest_event)"""
    if not events: return None, None, None, None, None, {}
    parsed = []
    for ev in events:
        if not isinstance(ev, dict): continue
        desc = (ev.get("description") or ev.get("movement") or ev.get("activity")
                or ev.get("eventType") or ev.get("statusCode") or "")
        loc  = (ev.get("location") or ev.get("portName") or ev.get("locationName")
                or ev.get("place") or "")
        date = parse_date(ev.get("date") or ev.get("eventDateTime") or ev.get("plannedDate")
                          or ev.get("actualDate") or "")
        vessel = (ev.get("vessel") or ev.get("vesselName") or ev.get("transportName") or "")
        eta_flag = ev.get("isETA") or "eta" in str(ev.get("eventType","")).lower()
        parsed.append({"desc": str(desc), "loc": str(loc), "date": date,
                       "vessel": str(vessel), "eta_flag": eta_flag})

    status = None
    for p in parsed:
        s = map_status(p["desc"])
        if s: status = s; break

    vessel = next((p["vessel"] for p in parsed if p["vessel"]
                   and p["vessel"].upper() not in ("","TRUCK","RAIL","BARGE")), "")
    pol = parsed[-1]["loc"] if parsed else ""
    pod = parsed[0]["loc"]  if parsed else ""
    eta = next((p["date"] for p in parsed if p["eta_flag"] and p["date"]), None)
    if not eta:
        now = datetime.utcnow().strftime("%Y-%m-%d")
        eta = next((p["date"] for p in parsed if p["date"] and p["date"] >= now), None)
    latest = parsed[0] if parsed else {}
    return status, eta, vessel, pol, pod, latest

def track_ocean(db: Session, shipment):
    container = (shipment.ref2 or "").strip()
    if not container:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}
    scac = resolve_scac(container, shipment.carrier or "")
    obj  = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()

    data, err = None, None
    source = ""

    if scac == "CMDU":
        data, err = track_cmacgm(container); source = "CMACGM"
    elif scac == "MSCU":
        data, err = track_msc(container); source = "MSC"
    elif scac == "MAEU":
        data, err = track_maersk(container); source = "MAERSK"

    # Fallback to shipsgo
    if (not data or err) and os.getenv("SHIPSGO_TOKEN",""):
        data, err = track_shipsgo(container, scac); source = "SHIPSGO"

    if not data:
        return {"ref": shipment.ref, "status": "error",
                "reason": err or "No data from any source", "scac": scac}

    events = extract_events_generic(data)
    new_status, new_eta, new_vessel, new_pol, new_pod, latest = parse_events(events)

    logger.info(f"[{source} {shipment.ref}] events={len(events)} status={new_status} "
                f"eta={new_eta} vessel={new_vessel}")

    # Save events
    for ev in events[:20]:
        if isinstance(ev, dict):
            desc = (ev.get("description") or ev.get("movement") or ev.get("activity") or "")
            loc  = (ev.get("location") or ev.get("portName") or ev.get("locationName") or "")
            if desc: crud.add_event(db, obj.id, str(loc), str(desc), new_status or "")

    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}->{new_status}")
    if new_vessel and new_vessel != obj.vessel:
        obj.vessel = new_vessel; changed.append(f"vessel->{new_vessel}")
    if new_eta:
        old_eta = obj.eta; obj.eta = new_eta
        if old_eta and old_eta != new_eta:
            changed.append(f"ETA {old_eta}->{new_eta}")
            try:
                import notifications as _n
                _n.send_eta_change_email(obj, old_eta, new_eta)
            except Exception as _e:
                logger.warning(f"ETA email: {_e}")
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()

    return {
        "ref": shipment.ref, "source": source, "scac": scac,
        "status": "updated" if changed else "no_change",
        "changed": changed, "new_status": new_status,
        "eta": new_eta, "vessel": new_vessel,
        "pol": new_pol, "pod": new_pod,
        "events_count": len(events),
        "latest_event": latest,
        "raw_sample": str(data)[:300] if not events else None
    }

def track_air(db: Session, shipment):
    return {"ref": shipment.ref, "status": "skipped",
            "reason": "Air tracking — add SHIPSGO_TOKEN for AWB"}

def track_and_update(db: Session, shipment):
    if (shipment.mode or "").strip().lower() == "air":
        return track_air(db, shipment)
    return track_ocean(db, shipment)

def run_auto_tracking(db: Session):
    active = db.query(models.Shipment).filter(
        models.Shipment.status.notin_(["Delivered"]),
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    return [track_and_update(db, s) for s in active]

def get_geojson(shipment):
    return {"type": "FeatureCollection", "features": []}
