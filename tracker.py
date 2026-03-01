import os, logging
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
    "evergreen":"EISU","evergreen line":"EISU",
    "cosco":"COSU","cosco shipping":"COSU",
    "one":"ONEY","ocean network express":"ONEY",
    "yang ming":"YMLU","yangming":"YMLU",
    "hmm":"HDMU","hyundai merchant":"HDMU",
    "zim":"ZIMU","zim integrated":"ZIMU",
    "pil":"PILU","apl":"APLU",
    "wan hai":"WHLC","wanhai":"WHLC",
    "oocl":"OOLU","orient overseas":"OOLU",
    "hamburg sud":"SUDU","hamburg sued":"SUDU",
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
        try: return datetime.strptime(s[:19].replace("Z",""), fmt[:len(fmt)]).strftime("%Y-%m-%d")
        except: pass
    return s[:10] if len(s) >= 10 else None

STATUS_MAP = {
    "EMPTY CONTAINER RETURNED":"Delivered","FULL IMPORT CONTAINER OUT GATED":"Delivered",
    "DELIVERED":"Delivered","GATE OUT":"Delivered","COMPLETED":"Delivered",
    "VESSEL DEPARTED":"Sailing","LOADED ON VESSEL":"Sailing","DEPARTED":"Sailing",
    "SAILING":"Sailing","EN ROUTE":"Sailing","IN TRANSIT":"Sailing",
    "VESSEL ARRIVED":"Arrived","ARRIVED":"Arrived","DISCHARGED":"Discharged",
    "DISCHARGED FROM VESSEL":"Discharged","UNLOADED":"Discharged",
    "GATE IN":"Pending","RECEIVED":"Pending","EMPTY TO SHIPPER":"Pending",
    "EXPORT CUSTOMS":"Pending","BOOKING CONFIRMED":"Pending",
}

def map_status_from_movement(movement):
    if not movement: return None
    upper = movement.upper().strip()
    for key, val in STATUS_MAP.items():
        if key in upper: return val
    return None

def track_ocean(db: Session, shipment):
    container = (shipment.ref2 or "").strip()
    if not container:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}

    scac = resolve_scac(container, shipment.carrier or "")
    if not scac:
        return {"ref": shipment.ref, "status": "error", "reason": "Could not resolve SCAC"}

    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()

    try:
        from tracktrace import ocean as tt_ocean
        ship = tt_ocean.container.create(scac=scac, container=container)
        updates = ship.updates or []
    except ImportError:
        return {"ref": shipment.ref, "status": "error",
                "reason": "tracktrace library not installed. Add it to requirements.txt"}
    except Exception as e:
        return {"ref": shipment.ref, "status": "error", "reason": str(e)}

    if not updates:
        return {"ref": shipment.ref, "status": "no_data",
                "reason": "No events returned — container may not be active yet"}

    # Latest event = most recent status
    latest = updates[0]
    new_status  = map_status_from_movement(latest.get("movement",""))
    new_vessel  = str(latest.get("vessel","") or "").strip()
    latest_date = parse_date(latest.get("date"))

    # Find ETA (last event in future or last event overall)
    new_eta = None
    for upd in reversed(updates):
        d = parse_date(upd.get("date"))
        if d and d >= datetime.utcnow().strftime("%Y-%m-%d"):
            new_eta = d; break
    if not new_eta and updates:
        new_eta = parse_date(updates[-1].get("date"))

    # POL = first event location, POD = last event location
    new_pol = str(updates[-1].get("location","") or "").strip() if updates else ""
    new_pod = str(updates[0].get("location","")  or "").strip() if updates else ""

    # Save all events to DB
    for upd in reversed(updates):
        loc  = str(upd.get("location","") or "")
        desc = str(upd.get("movement","") or "")
        d    = parse_date(upd.get("date"))
        if desc:
            crud.add_event(db, obj.id, loc, f"{desc}" + (f" ({d})" if d else ""),
                           new_status or "")

    changed = []
    if new_status and new_status != obj.status:
        old = obj.status; obj.status = new_status
        changed.append(f"status {old}→{new_status}")
    if new_vessel and new_vessel.upper() not in ("TRUCK","RAIL","") and new_vessel != obj.vessel:
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
    if new_pol and not obj.pol: obj.pol = new_pol
    if new_pod and not obj.pod: obj.pod = new_pod
    obj.last_tracked = datetime.utcnow().isoformat()
    db.commit()

    logger.info(f"[TT {shipment.ref}] Done. events={len(updates)} changed={changed} "
                f"status={new_status} vessel={new_vessel} eta={new_eta}")
    return {
        "ref": shipment.ref, "scac": scac,
        "status": "updated" if changed else "no_change",
        "changed": changed,
        "new_status": new_status, "eta": new_eta,
        "vessel": new_vessel, "pol": new_pol, "pod": new_pod,
        "events_count": len(updates),
        "latest_event": {"movement": latest.get("movement"), "location": latest.get("location"),
                         "date": str(latest.get("date",""))}
    }

def track_air(db: Session, shipment):
    return {"ref": shipment.ref, "status": "skipped",
            "reason": "Air tracking not supported — add SHIPSGO_TOKEN for AWB tracking"}

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
