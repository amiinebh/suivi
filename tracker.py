import requests, os, time, logging
from datetime import datetime
from sqlalchemy.orm import Session
import models, crud

logger = logging.getLogger("tracker")
logging.basicConfig(level=logging.INFO)

T49_KEY  = os.getenv("TERMINAL49_API_KEY", "")
T49_BASE = "https://api.terminal49.com/v2"

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
    "msc":"MSCU","mediterranean":"MSCU","mediterranean shipping":"MSCU",
    "maersk":"MAEU","maersk line":"MAEU",
    "hapag":"HLCU","hapag-lloyd":"HLCU","hapag lloyd":"HLCU","hl":"HLCU",
    "evergreen":"EISU","evergreen line":"EISU",
    "cosco":"COSU","cosco shipping":"COSU",
    "one":"ONEY","ocean network express":"ONEY",
    "yang ming":"YMLU","yangming":"YMLU",
    "hmm":"HDMU","hyundai":"HDMU","hyundai merchant":"HDMU",
    "zim":"ZIMU","zim integrated":"ZIMU",
    "pil":"PILU","apl":"APLU",
    "wan hai":"WHLC","wanhai":"WHLC",
    "oocl":"OOLU","orient overseas":"OOLU",
    "hamburg sud":"SUDU","hamburg süd":"SUDU",
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

STATUS_MAP = {
    "PENDING":"Pending","CREATED":"Pending","AWAITING_MANIFEST":"Pending",
    "IN_TRANSIT":"Sailing","SAILING":"Sailing","LOADED":"Sailing","EN_ROUTE":"Sailing",
    "ARRIVED":"Arrived","AT_DESTINATION":"Arrived","DISCHARGED":"Discharged",
    "DELIVERED":"Delivered","GATE_OUT":"Delivered","EMPTY_RETURNED":"Delivered",
    "COMPLETED":"Delivered","FAILED":"Pending","TRACKING_STOPPED":"Pending",
}
def map_status(raw):
    if not raw: return None
    upper = str(raw).upper().strip().replace("-","_").replace(" ","_")
    return STATUS_MAP.get(upper) or None

def t49_headers():
    return {
        "Authorization": f"Token {T49_KEY}",
        "Content-Type": "application/vnd.api+json",
        "Accept": "application/json"
    }

def track_ocean(db: Session, shipment):
    container = (shipment.ref2 or "").strip()
    if not container:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}
    if not T49_KEY:
        return {"ref": shipment.ref, "status": "error",
                "reason": "TERMINAL49_API_KEY not set in Railway env vars — add it now!"}

    scac = resolve_scac(container, shipment.carrier or "")
    obj  = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()

    # ── STEP 1: Create tracking request if no shipsgo_id ─────────────
    t49_tracking_id = obj.shipsgo_id  # reusing shipsgo_id column to store T49 tracking request UUID
    shipment_uuid   = None

    if not t49_tracking_id:
        attrs = {
            "request_type": "container",
            "request_number": container,
        }
        if scac: attrs["scac"] = scac
        if shipment.ref: attrs["ref_numbers"] = [shipment.ref]

        body = {"data": {"type": "tracking_request", "attributes": attrs}}
        logger.info(f"[T49 {shipment.ref}] POST tracking_request body={attrs}")

        r = requests.post(f"{T49_BASE}/tracking_requests",
                          headers=t49_headers(), json=body, timeout=25)
        logger.info(f"[T49 {shipment.ref}] POST {r.status_code}: {r.text[:500]}")

        if r.status_code == 401:
            return {"ref": shipment.ref, "status": "error",
                    "reason": "Unauthorized — check TERMINAL49_API_KEY in Railway"}
        if r.status_code == 422:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"Invalid data (422): {r.text[:300]}"}
        if r.status_code not in (200, 201):
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"POST {r.status_code}: {r.text[:300]}"}

        try: resp = r.json()
        except: return {"ref": shipment.ref, "status": "error",
                        "reason": f"Bad JSON: {r.text[:200]}"}

        t49_tracking_id = (resp.get("data") or {}).get("id")
        if not t49_tracking_id:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"No tracking request id in response: {r.text[:200]}"}

        # Save tracking request ID (stored in shipsgo_id column for now)
        obj.shipsgo_id = hash(t49_tracking_id) % 2147483647  # store int hash
        obj.note = (obj.note or "") + f"\nt49_id:{t49_tracking_id}"
        db.commit()
        logger.info(f"[T49 {shipment.ref}] Tracking request created: {t49_tracking_id}")
        time.sleep(3)  # Give T49 a moment to process

        # Check tracking request status → get shipment UUID
        tr_status = (resp.get("data",{}).get("attributes",{}) or {}).get("status","")
        tracked   = (resp.get("data",{}).get("relationships",{})
                        .get("tracked_object",{}).get("data") or {})
        shipment_uuid = tracked.get("id")

    else:
        # Try to find saved t49_id in note field
        note = obj.note or ""
        import re
        m = re.search(r"t49_id:([a-f0-9\-]{36})", note)
        t49_tracking_id = m.group(1) if m else None

    # ── STEP 2: Poll tracking request to get shipment UUID ───────────
    if t49_tracking_id and not shipment_uuid:
        r2 = requests.get(f"{T49_BASE}/tracking_requests/{t49_tracking_id}",
                          headers=t49_headers(), timeout=25)
        logger.info(f"[T49 {shipment.ref}] GET tracking_req {r2.status_code}: {r2.text[:400]}")
        if r2.status_code == 200:
            try:
                d2 = r2.json()
                tr_attrs  = (d2.get("data",{}).get("attributes") or {})
                tracked   = (d2.get("data",{}).get("relationships",{})
                               .get("tracked_object",{}).get("data") or {})
                shipment_uuid = tracked.get("id")
                tr_status = tr_attrs.get("status","")
                if tr_attrs.get("failed_reason"):
                    return {"ref": shipment.ref, "status": "error",
                            "reason": f"T49 failed: {tr_attrs.get('failed_reason')}"}
            except: pass

    if not shipment_uuid:
        return {"ref": shipment.ref, "status": "pending",
                "reason": "T49 still processing — will retry next cycle",
                "t49_tracking_id": t49_tracking_id}

    # ── STEP 3: Fetch full shipment details ──────────────────────────
    r3 = requests.get(f"{T49_BASE}/shipments/{shipment_uuid}?include=containers",
                      headers=t49_headers(), timeout=25)
    logger.info(f"[T49 {shipment.ref}] GET shipment {r3.status_code}: {r3.text[:600]}")
    if r3.status_code != 200:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET shipment {r3.status_code}: {r3.text[:200]}"}

    try: sdata = r3.json()
    except: return {"ref": shipment.ref, "status": "error",
                    "reason": f"Bad JSON from shipment: {r3.text[:200]}"}

    attrs  = (sdata.get("data",{}).get("attributes") or {})
    rels   = (sdata.get("data",{}).get("relationships") or {})
    incl   = sdata.get("included") or []

    # T49 shipment fields
    raw_status  = str(attrs.get("status") or "")
    new_status  = map_status(raw_status)
    new_eta     = parse_date(attrs.get("pod_eta_at") or attrs.get("destination_eta_at")
                             or attrs.get("eta"))
    new_etd     = parse_date(attrs.get("pol_etd_at") or attrs.get("origin_etd_at"))
    new_pol     = (attrs.get("pol") or attrs.get("port_of_lading_name") or "")
    new_pod     = (attrs.get("pod") or attrs.get("port_of_discharge_name") or "")
    new_carrier = (attrs.get("shipping_line_name") or attrs.get("carrier") or "")

    # Vessel from containers in included
    new_vessel = ""
    for item in incl:
        if item.get("type") == "container":
            c_attrs = item.get("attributes") or {}
            v = c_attrs.get("vessel_name") or c_attrs.get("last_vessel_name") or ""
            if v: new_vessel = v; break
            # Also grab transport events
            for ev in (c_attrs.get("transport_events") or []):
                loc  = ev.get("location","") or ""
                desc = ev.get("description","") or ev.get("event","") or ev.get("activity","") or ""
                if desc: crud.add_event(db, obj.id, str(loc), str(desc), raw_status)

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
                logger.warning(f"ETA email err: {_e}")
    if new_etd: obj.etd = new_etd
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    if new_carrier and not obj.carrier: obj.carrier = new_carrier
    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()

    logger.info(f"[T49 {shipment.ref}] Done. changed={changed} eta={new_eta} "
                f"status={new_status} vessel={new_vessel}")
    return {
        "ref": shipment.ref, "t49_shipment_id": shipment_uuid,
        "status": "updated" if changed else "no_change",
        "changed": changed, "raw_status": raw_status,
        "eta": new_eta, "vessel": new_vessel, "scac_used": scac
    }


def track_air(db: Session, shipment):
    """Air shipments — T49 is ocean only, return info message."""
    return {"ref": shipment.ref, "status": "skipped",
            "reason": "Air tracking not supported by Terminal49 — add SHIPSGO_TOKEN for air"}


def track_and_update(db: Session, shipment):
    mode = (shipment.mode or "").strip().lower()
    if mode == "air":
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
