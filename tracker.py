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

# ── Carrier name → SCAC code map (user-friendly input → API code) ─────────────
CARRIER_NAME_TO_SCAC = {
    "cma": "CMDU", "cma cgm": "CMDU", "cmacgm": "CMDU", "cma-cgm": "CMDU",
    "msc": "MSCU", "mediterranean": "MSCU",
    "maersk": "MAEU", "maersk line": "MAEU",
    "hapag": "HLCU", "hapag-lloyd": "HLCU", "hapag lloyd": "HLCU",
    "evergreen": "EISU", "evergreen line": "EISU",
    "cosco": "COSU", "cosco shipping": "COSU",
    "one": "ONEY", "ocean network express": "ONEY",
    "yang ming": "YMLU", "yangming": "YMLU",
    "hyundai": "HDMU", "hmm": "HDMU",
    "zim": "ZIMU",
    "pil": "PILU", "pacific international": "PILU",
    "apl": "APLU",
    "wan hai": "WHLC", "wanhai": "WHLC",
}

# ── Container prefix → SCAC (auto-detect carrier from container number) ───────
PREFIX_TO_SCAC = {
    # CMA CGM group
    "CMAU":"CMDU","CGMU":"CMDU","SEKU":"CMDU","FSCU":"CMDU","GESU":"CMDU",
    "TCNU":"CMDU","TLLU":"CMDU","CSFU":"CMDU","ECMU":"CMDU","SMUU":"CMDU",
    "APHU":"CMDU","APLU":"CMDU","ANNU":"CMDU","CMNU":"CMDU","CSOU":"CMDU",
    # MSC
    "MSCU":"MSCU","MEDU":"MSCU","MSDU":"MSCU","BMOU":"MSCU",
    # Maersk
    "MAEU":"MAEU","MSKU":"MAEU","MCPU":"MAEU","MRKU":"MAEU",
    # Hapag-Lloyd
    "HLCU":"HLCU","HLXU":"HLCU","UASC":"HLCU",
    # Evergreen
    "EISU":"EISU","EMCU":"EISU","EGHU":"EISU","EVGU":"EISU","TRIU":"EISU",
    # COSCO
    "CCLU":"COSU","CBHU":"COSU","COSU":"COSU","COCU":"COSU",
    # ONE
    "ONEY":"ONEY","NYKU":"ONEY","MOLU":"ONEY","KMTU":"ONEY",
    # Yang Ming
    "YMLU":"YMLU","YMTU":"YMLU",
    # HMM
    "HMMU":"HDMU","HDMU":"HDMU",
    # ZIM
    "ZIMU":"ZIMU","ZCSU":"ZIMU",
    # PIL
    "PILU":"PILU",
    # APL (already under CMA but separate SCAC)
    "APZU":"APLU",
    # Wan Hai
    "WHLU":"WHLC",
}

def headers():
    return {"X-Shipsgo-User-Token": SHIPSGO_TOKEN,
            "Content-Type": "application/json", "Accept": "application/json"}

def resolve_scac(container_no: str, carrier_input: str) -> str:
    """Resolve SCAC from container prefix or carrier name input."""
    # 1. Try carrier name input (what user typed e.g. "CMA", "Maersk")
    if carrier_input:
        key = carrier_input.lower().strip()
        if key in CARRIER_NAME_TO_SCAC:
            return CARRIER_NAME_TO_SCAC[key]
        # If it looks like a SCAC already (4 uppercase letters)
        if len(carrier_input) == 4 and carrier_input.upper() == carrier_input:
            return carrier_input.upper()
        # Partial match
        for name, scac in CARRIER_NAME_TO_SCAC.items():
            if key in name or name in key:
                return scac

    # 2. Auto-detect from container prefix (first 4 chars)
    prefix = (container_no or "")[:4].upper()
    if prefix in PREFIX_TO_SCAC:
        return PREFIX_TO_SCAC[prefix]

    return ""

def parse_date(v):
    if not v: return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ","%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S%z","%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M","%Y-%m-%d"):
        try: return datetime.strptime(s[:26].rstrip("Z"), fmt.rstrip("Z")).strftime("%Y-%m-%d")
        except: pass
    return s[:10] if len(s) >= 10 else None

STATUS_MAP = {
    "inprogress":"Sailing","in_progress":"Sailing","sailing":"Sailing",
    "enroute":"Sailing","en_route":"Sailing","in_transit":"Sailing",
    "discharged":"Discharged","arrived":"Arrived",
    "delivered":"Delivered","completed":"Delivered",
    "delayed":"Delayed","rollover":"Delayed",
    "pending":"Pending","created":"Pending","booked":"Pending",
    "registered":"Pending","untracked":"Pending","inprogress_import":"Pending",
}

def map_status(raw):
    if not raw: return None
    r = str(raw).lower().replace("-","_").replace(" ","_")
    return STATUS_MAP.get(r) or next(
        (v for k,v in STATUS_MAP.items() if k in r), None)

def safe_ref(ref):
    """Ensure reference meets Shipsgo 5-128 char requirement."""
    ref = (ref or "").strip()
    if len(ref) < 5:
        ref = ref + "-FTP"  # pad short refs
    return ref[:128]

def track_ocean(db: Session, shipment):
    no = (shipment.ref2 or "").strip()
    if not no:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}
    if not SHIPSGO_TOKEN:
        return {"ref": shipment.ref, "status": "error", "reason": "SHIPSGO_TOKEN not set in Railway env vars"}

    scac = resolve_scac(no, shipment.carrier or "")
    logger.info(f"[{shipment.ref}] container={no} carrier_input={shipment.carrier!r} resolved_scac={scac!r}")

    shipsgo_id = shipment.shipsgo_id

    if not shipsgo_id:
        body = {"container_number": no}
        if scac:
            body["carrier"] = scac
        if shipment.booking_no:
            body["booking_number"] = shipment.booking_no
        # reference must be 5-128 chars
        body["reference"] = safe_ref(shipment.ref)
        # Add client email as follower if set
        if shipment.client_email:
            body["followers"] = [shipment.client_email]

        logger.info(f"[{shipment.ref}] POST body: {body}")
        r = requests.post(OCEAN, headers=headers(), json=body, timeout=25)
        logger.info(f"[{shipment.ref}] POST {r.status_code}: {r.text[:400]}")

        d = {}
        try: d = r.json()
        except: pass

        if r.status_code in (200, 201):
            shipsgo_id = (d.get("shipment") or {}).get("id")
        elif r.status_code == 409:
            # Already exists — grab the existing id
            shipsgo_id = (d.get("shipment") or {}).get("id")
            if not shipsgo_id:
                # Some 409 responses include it differently
                shipsgo_id = d.get("id") or (d.get("data") or {}).get("id")
            logger.info(f"[{shipment.ref}] 409 conflict — existing id={shipsgo_id}")
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:400]}"}

        if not shipsgo_id:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"No shipsgo_id in response. body={r.text[:300]}"}

        time.sleep(2)

    # Save shipsgo_id
    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
    if obj and not obj.shipsgo_id:
        obj.shipsgo_id = shipsgo_id
        db.commit()

    # Fetch details
    r2 = requests.get(f"{OCEAN}/{shipsgo_id}", headers=headers(), timeout=25)
    logger.info(f"[{shipment.ref}] GET {r2.status_code}: {r2.text[:600]}")
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:300]}"}

    data  = r2.json()
    # v2 ocean GET: {"message":"SUCCESS","shipment":{...}}
    ship  = data.get("shipment") or data.get("data") or data or {}
    if isinstance(ship, list): ship = ship[0] if ship else {}

    route = ship.get("route") or {}
    pod_d = route.get("port_of_discharge") or {}
    pol_d = route.get("port_of_loading") or {}

    new_eta = (parse_date(pod_d.get("date_of_discharge")) or
               parse_date(pod_d.get("date_of_discharge_initial")) or
               parse_date(pod_d.get("eta")) or
               parse_date(ship.get("eta")))
    new_etd = (parse_date(pol_d.get("date_of_loading")) or
               parse_date(pol_d.get("date_of_loading_initial")) or
               parse_date(pol_d.get("etd")) or
               parse_date(ship.get("etd")))

    raw_status = ship.get("status","")
    new_status = map_status(str(raw_status))

    def port_name(d):
        if not d: return ""
        return (d.get("name") or
                (d.get("location") or {}).get("name") or
                (d.get("port") or {}).get("name") or "")

    new_pol = port_name(pol_d)
    new_pod = port_name(pod_d)

    # Vessel
    containers = ship.get("containers") or []
    if isinstance(containers, dict): containers = [containers]
    new_vessel = ""
    for c in (containers if isinstance(containers,list) else []):
        if not isinstance(c,dict): continue
        v = c.get("vessel") or {}
        name = v.get("name","") if isinstance(v,dict) else str(v)
        if name: new_vessel = name; break
    if not new_vessel:
        new_vessel = ship.get("vessel_name") or ""

    # Carrier
    carrier_info = ship.get("carrier") or {}
    new_carrier = (carrier_info.get("name","") if isinstance(carrier_info,dict)
                   else str(carrier_info)) if carrier_info else ""

    # Events / movements
    movements = ship.get("movements") or ship.get("events") or []
    if movements and isinstance(movements, list):
        for mv in movements:
            if not isinstance(mv,dict): continue
            ts   = parse_date(mv.get("timestamp") or mv.get("date",""))
            desc = (mv.get("description") or mv.get("event") or mv.get("status",""))
            loc  = ((mv.get("location") or {}).get("name","") if isinstance(mv.get("location"),dict)
                    else str(mv.get("location","") or ""))
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
        if old_eta != new_eta:
            changed.append(f"ETA {old_eta}→{new_eta}")
            if old_eta:
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
    return {"ref": shipment.ref, "shipsgo_id": shipsgo_id,
            "status": "updated" if changed else "no_change",
            "changed": changed, "raw_status": raw_status,
            "eta": new_eta, "vessel": new_vessel, "scac_used": scac}

def track_air(db: Session, shipment):
    awb = (shipment.ref2 or "").strip()
    if not awb: return {"ref": shipment.ref, "status": "skipped", "reason": "No AWB"}
    if not SHIPSGO_TOKEN:
        return {"ref": shipment.ref, "status": "error", "reason": "SHIPSGO_TOKEN not set"}

    body = {"awb_number": awb, "reference": safe_ref(shipment.ref)}
    if shipment.client_email:
        body["followers"] = [shipment.client_email]

    shipsgo_id = shipment.shipsgo_id
    if not shipsgo_id:
        r = requests.post(AIR, headers=headers(), json=body, timeout=25)
        logger.info(f"[AIR {shipment.ref}] POST {r.status_code}: {r.text[:300]}")
        d = {}
        try: d = r.json()
        except: pass
        if r.status_code in (200, 201, 409):
            shipsgo_id = (d.get("shipment") or {}).get("id") or d.get("id")
        else:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:300]}"}
        if not shipsgo_id:
            return {"ref": shipment.ref, "status": "error", "reason": "No shipsgo_id"}
        time.sleep(2)

    r2 = requests.get(f"{AIR}/{shipsgo_id}", headers=headers(), timeout=25)
    if r2.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET {r2.status_code}: {r2.text[:300]}"}

    data  = r2.json()
    ship  = data.get("shipment") or data.get("data") or {}
    if isinstance(ship, list): ship = ship[0] if ship else {}
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
    if new_eta: obj.eta = new_eta; changed.append(f"ETA→{new_eta}")
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
    return track_air(db, shipment) if (shipment.mode or "").lower() == "air" else track_ocean(db, shipment)

def run_auto_tracking(db: Session):
    active = db.query(models.Shipment).filter(
        models.Shipment.status.notin_(["Delivered"]),
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    return [track_and_update(db, s) for s in active]

def get_geojson(shipment):
    """Return a basic GeoJSON stub — real vessel position via Shipsgo map tokens."""
    return {"type":"FeatureCollection","features":[]}
