import requests, os, time, logging
from datetime import datetime
from sqlalchemy.orm import Session
import models, crud

logger = logging.getLogger("tracker")
logging.basicConfig(level=logging.INFO)

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN") or os.getenv("SHIPSGO_API_KEY","")
BASE  = "https://api.shipsgo.com/v2"
OCEAN_URL = f"{BASE}/ocean/shipments"
AIR_URL   = f"{BASE}/air/shipments"

# Carrier name → SCAC (from official Shipsgo /ocean/carriers endpoint)
CARRIER_NAME_TO_SCAC = {
    "cma": "CMDU", "cma cgm": "CMDU", "cmacgm": "CMDU", "cma-cgm": "CMDU",
    "cma cgm group": "CMDU", "cma_cgm": "CMDU",
    "msc": "MSCU", "mediterranean": "MSCU", "mediterranean shipping": "MSCU",
    "maersk": "MAEU", "maersk line": "MAEU", "a.p. moller": "MAEU",
    "hapag": "HLCU", "hapag-lloyd": "HLCU", "hapag lloyd": "HLCU", "hl": "HLCU",
    "evergreen": "EISU", "evergreen line": "EISU", "evergreen marine": "EISU",
    "cosco": "COSU", "cosco shipping": "COSU", "cosco container": "COSU",
    "one": "ONEY", "ocean network express": "ONEY",
    "yang ming": "YMLU", "yangming": "YMLU", "yang ming marine": "YMLU",
    "hmm": "HDMU", "hyundai": "HDMU", "hyundai merchant": "HDMU",
    "zim": "ZIMU", "zim integrated": "ZIMU",
    "pil": "PILU", "pacific international lines": "PILU",
    "apl": "APLU", "american president": "APLU",
    "wan hai": "WHLC", "wanhai": "WHLC", "wan hai lines": "WHLC",
    "oocl": "OOLU", "orient overseas": "OOLU",
    "hamburg sud": "SUDU", "hamburg süd": "SUDU",
    "sealand": "SEAU",
    "safmarine": "SAFM",
}

# Container prefix → SCAC
PREFIX_TO_SCAC = {
    # CMA CGM group (many prefixes)
    "CMAU":"CMDU","CGMU":"CMDU","SEKU":"CMDU","FSCU":"CMDU","GESU":"CMDU",
    "TCNU":"CMDU","TLLU":"CMDU","CSFU":"CMDU","ECMU":"CMDU","SMUU":"CMDU",
    "APHU":"CMDU","ANNU":"CMDU","CMNU":"CMDU","CSOU":"CMDU","LYKU":"CMDU",
    # MSC
    "MSCU":"MSCU","MEDU":"MSCU","MSDU":"MSCU","BMOU":"MSCU","MSOU":"MSCU",
    # Maersk
    "MAEU":"MAEU","MSKU":"MAEU","MCPU":"MAEU","MRKU":"MAEU","MRKU":"MAEU",
    # Hapag-Lloyd
    "HLCU":"HLCU","HLXU":"HLCU","UASU":"HLCU",
    # Evergreen
    "EISU":"EISU","EMCU":"EISU","EGHU":"EISU","EVGU":"EISU","TRIU":"EISU","TCKU":"EISU",
    # COSCO
    "CCLU":"COSU","CBHU":"COSU","COSU":"COSU","COCU":"COSU","CSNU":"COSU",
    # ONE
    "ONEY":"ONEY","NYKU":"ONEY","MOLU":"ONEY","KMTU":"ONEY","TEXU":"ONEY",
    # Yang Ming
    "YMLU":"YMLU","YMTU":"YMLU",
    # HMM
    "HMMU":"HDMU","HDMU":"HDMU",
    # ZIM
    "ZIMU":"ZIMU","ZCSU":"ZIMU",
    # PIL
    "PILU":"PILU","PCLU":"PILU",
    # APL
    "APZU":"APLU","APLU":"APLU",
    # Wan Hai
    "WHLU":"WHLC",
    # OOCL
    "OOLU":"OOLU","OOCU":"OOLU",
    # Hamburg Sud
    "SUDU":"SUDU","LGBU":"SUDU",
}

def api_headers():
    return {
        "X-Shipsgo-User-Token": SHIPSGO_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def resolve_scac(container_no: str, carrier_input: str) -> str:
    """Resolve SCAC from user-provided carrier name or container prefix."""
    if carrier_input:
        key = carrier_input.lower().strip()
        # Direct lookup
        if key in CARRIER_NAME_TO_SCAC:
            return CARRIER_NAME_TO_SCAC[key]
        # Already a valid 4-char SCAC
        if len(carrier_input) == 4 and carrier_input.isalpha():
            return carrier_input.upper()
        # Partial match
        for name, scac in CARRIER_NAME_TO_SCAC.items():
            if key in name or name in key:
                return scac
    # Auto-detect from container number prefix
    prefix = (container_no or "")[:4].upper()
    return PREFIX_TO_SCAC.get(prefix, "")

def parse_date(v):
    if not v: return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            clean = s[:26].replace("Z","")
            return datetime.strptime(clean, fmt.replace("Z","")).strftime("%Y-%m-%d")
        except: pass
    return s[:10] if len(s) >= 10 else None

# Official Shipsgo v2 status values
STATUS_MAP = {
    "INPROGRESS": "Sailing", "IN_PROGRESS": "Sailing",
    "SAILING": "Sailing",
    "DISCHARGED": "Discharged",
    "ARRIVED": "Arrived",
    "DELIVERED": "Delivered", "COMPLETED": "Delivered",
    "DELAYED": "Delayed", "ROLLOVER": "Delayed",
    "PENDING": "Pending", "CREATED": "Pending", "BOOKED": "Pending",
    "REGISTERED": "Pending", "UNTRACKED": "Pending",
    "EN_ROUTE": "Sailing", "ENROUTE": "Sailing",
}

def map_status(raw: str) -> str:
    if not raw: return None
    upper = str(raw).upper().strip().replace("-","_").replace(" ","_")
    return STATUS_MAP.get(upper) or STATUS_MAP.get(upper.replace("_","")) or None

def track_ocean(db: Session, shipment):
    container = (shipment.ref2 or "").strip()
    if not container:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}
    if not SHIPSGO_TOKEN:
        return {"ref": shipment.ref, "status": "error",
                "reason": "SHIPSGO_TOKEN not set in Railway env vars"}

    scac = resolve_scac(container, shipment.carrier or "")
    shipsgo_id = shipment.shipsgo_id

    # ── STEP 1: Register with Shipsgo if no shipsgo_id ──────────────────
    if not shipsgo_id:
        body = {"container_number": container}
        if scac:            body["carrier"] = scac
        if shipment.ref:    body["reference"] = shipment.ref
        if shipment.booking_no: body["booking_number"] = shipment.booking_no
        if shipment.client_email:
            body["followers"] = [shipment.client_email]

        logger.info(f"[{shipment.ref}] POST body={body}")
        r = requests.post(OCEAN_URL, headers=api_headers(), json=body, timeout=25)
        logger.info(f"[{shipment.ref}] POST {r.status_code}: {r.text[:400]}")

        try: resp = r.json()
        except: resp = {}

        if r.status_code in (200, 201, 409):
            # Both success and duplicate return shipment.id
            shipsgo_id = (resp.get("shipment") or {}).get("id")
        elif r.status_code == 402:
            return {"ref": shipment.ref, "status": "error", "reason": "NOT_ENOUGH_CREDITS"}
        elif r.status_code == 401:
            return {"ref": shipment.ref, "status": "error", "reason": "Unauthorized — check SHIPSGO_TOKEN in Railway"}
        elif r.status_code == 422:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"Invalid payload (422): {r.text[:300]}"}
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:300]}"}

        if not shipsgo_id:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"No shipment.id in response: {r.text[:200]}"}

        # Save immediately
        obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
        obj.shipsgo_id = shipsgo_id
        db.commit()
        logger.info(f"[{shipment.ref}] Registered shipsgo_id={shipsgo_id}")
        time.sleep(2)  # Let Shipsgo process before fetching details
    else:
        obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()

    # ── STEP 2: Fetch full details ────────────────────────────────────────
    r2 = requests.get(f"{OCEAN_URL}/{shipsgo_id}", headers=api_headers(), timeout=25)
    logger.info(f"[{shipment.ref}] GET {r2.status_code}: {r2.text[:600]}")
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:200]}"}

    data = r2.json()
    # Official response: {"message":"SUCCESS","shipment":{...}}
    ship = data.get("shipment") or {}

    raw_status = str(ship.get("status") or "")
    new_status = map_status(raw_status)

    # Route info
    route  = ship.get("route") or {}
    pol_d  = route.get("port_of_loading") or {}
    pod_d  = route.get("port_of_discharge") or {}

    # port name: location.name
    new_pol = (pol_d.get("location") or {}).get("name","")
    new_pod = (pod_d.get("location") or {}).get("name","")

    # dates
    new_etd = parse_date(pol_d.get("date_of_loading") or pol_d.get("date_of_loading_initial"))
    new_eta = parse_date(pod_d.get("date_of_discharge") or pod_d.get("date_of_discharge_initial"))

    # carrier from response
    carrier_info = ship.get("carrier") or {}
    new_carrier = carrier_info.get("name","") if isinstance(carrier_info,dict) else ""

    # vessel from containers[].movements or containers[].vessel
    containers = ship.get("containers") or []
    new_vessel = ""
    for c in (containers if isinstance(containers,list) else []):
        if not isinstance(c,dict): continue
        v = c.get("vessel") or {}
        name = v.get("name","") if isinstance(v,dict) else str(v or "")
        if name: new_vessel = name; break

    # Save movements/events
    for c in (containers if isinstance(containers,list) else []):
        if not isinstance(c,dict): continue
        for mv in (c.get("movements") or []):
            if not isinstance(mv,dict): continue
            loc_d = mv.get("location") or {}
            loc   = loc_d.get("name","") if isinstance(loc_d,dict) else str(loc_d or "")
            desc  = mv.get("description") or mv.get("event") or mv.get("status","")
            if desc:
                crud.add_event(db, obj.id, loc, desc, raw_status)

    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}→{new_status}")
        crud.add_event(db, obj.id, "", f"Status: {old} → {new_status}", new_status)
    if new_vessel and new_vessel != obj.vessel:
        obj.vessel = new_vessel; changed.append(f"vessel→{new_vessel}")
    if new_eta:
        old_eta = obj.eta; obj.eta = new_eta
        if old_eta and old_eta != new_eta:
            changed.append(f"ETA {old_eta}→{new_eta}")
            try:
                import notifications as _n
                _n.send_eta_change_email(obj, old_eta, new_eta)
            except Exception as _e:
                logger.warning(f"ETA email: {_e}")
    if new_etd: obj.etd = new_etd
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    if new_carrier and not obj.carrier: obj.carrier = new_carrier
    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()

    logger.info(f"[{shipment.ref}] Done. changed={changed} eta={new_eta} status={new_status} vessel={new_vessel}")
    return {
        "ref": shipment.ref, "shipsgo_id": shipsgo_id,
        "status": "updated" if changed else "no_change",
        "changed": changed, "raw_status": raw_status,
        "eta": new_eta, "vessel": new_vessel, "scac_used": scac
    }


def track_air(db: Session, shipment):
    awb = (shipment.ref2 or "").strip()
    if not awb: return {"ref": shipment.ref, "status": "skipped", "reason": "No AWB number"}
    if not SHIPSGO_TOKEN:
        return {"ref": shipment.ref, "status": "error", "reason": "SHIPSGO_TOKEN not set"}

    shipsgo_id = shipment.shipsgo_id
    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()

    if not shipsgo_id:
        body = {"awb_number": awb}
        if shipment.ref: body["reference"] = shipment.ref
        if shipment.client_email: body["followers"] = [shipment.client_email]

        r = requests.post(AIR_URL, headers=api_headers(), json=body, timeout=25)
        logger.info(f"[AIR {shipment.ref}] POST {r.status_code}: {r.text[:300]}")
        try: resp = r.json()
        except: resp = {}

        if r.status_code in (200, 201, 409):
            shipsgo_id = (resp.get("shipment") or {}).get("id")
        elif r.status_code == 402:
            return {"ref": shipment.ref, "status": "error", "reason": "NOT_ENOUGH_CREDITS"}
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:200]}"}
        if not shipsgo_id:
            return {"ref": shipment.ref, "status": "error", "reason": f"No id in response: {r.text[:200]}"}
        obj.shipsgo_id = shipsgo_id; db.commit()
        time.sleep(2)

    r2 = requests.get(f"{AIR_URL}/{shipsgo_id}", headers=api_headers(), timeout=25)
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:200]}"}

    data = r2.json()
    ship = data.get("shipment") or {}
    route = ship.get("route") or {}
    dest  = route.get("destination") or {}
    orig  = route.get("origin") or {}

    raw_status = str(ship.get("status") or "")
    new_status = map_status(raw_status)
    new_eta = parse_date(dest.get("date_of_rcf") or dest.get("date_of_rcf_initial"))
    new_etd = parse_date(orig.get("date_of_dep") or orig.get("date_of_dep_initial"))
    airline = ship.get("airline") or {}
    new_carrier = airline.get("name","") if isinstance(airline,dict) else ""
    new_pod = ((dest.get("location") or {}).get("name",""))
    new_pol = ((orig.get("location") or {}).get("name",""))

    for mv in (ship.get("movements") or []):
        if not isinstance(mv,dict): continue
        loc_d = mv.get("location") or {}
        loc   = loc_d.get("name","") if isinstance(loc_d,dict) else ""
        desc  = mv.get("description") or mv.get("event") or mv.get("status","")
        if desc: crud.add_event(db, obj.id, loc, desc, raw_status)

    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}→{new_status}")
        crud.add_event(db, obj.id, "", f"Status: {old}→{new_status}", new_status)
    if new_eta: obj.eta = new_eta; changed.append(f"ETA→{new_eta}")
    if new_etd: obj.etd = new_etd
    if new_carrier and not obj.carrier: obj.carrier = new_carrier
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()

    return {"ref": shipment.ref, "shipsgo_id": shipsgo_id,
            "status": "updated" if changed else "no_change", "changed": changed}


def track_and_update(db: Session, shipment):
    return track_air(db, shipment) if (shipment.mode or "").strip().lower() == "air"            else track_ocean(db, shipment)

def run_auto_tracking(db: Session):
    active = db.query(models.Shipment).filter(
        models.Shipment.status.notin_(["Delivered"]),
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    return [track_and_update(db, s) for s in active]

def get_geojson(shipment):
    return {"type": "FeatureCollection", "features": []}
