import requests, os
from datetime import datetime
from sqlalchemy.orm import Session
import models

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN", "3fd0583a-9281-4c30-8d9d-ececa0fff69c")
SHIPSGO_URL   = "https://shipsgo.com/api/v1.2/ContainerService/GetContainerInfo"

# â”€â”€ Shipsgo exact shipping line names â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Must match exactly as in Shipsgo's list. If unknown â†’ "OTHERS"
CARRIER_MAP = {
    "cma":         "CMA CGM",
    "cma cgm":     "CMA CGM",
    "cmacgm":      "CMA CGM",
    "hapag":       "Hapag-Lloyd",
    "hapag-lloyd": "Hapag-Lloyd",
    "hapag lloyd": "Hapag-Lloyd",
    "hl":          "Hapag-Lloyd",
    "maersk":      "Maersk",
    "msc":         "MSC",
    "evergreen":   "Evergreen",
    "cosco":       "COSCO",
    "coscol":      "COSCO",
    "one":         "ONE",
    "yang ming":   "Yang Ming",
    "yangming":    "Yang Ming",
    "hmm":         "HMM",
    "pil":         "PIL",
    "zim":         "ZIM",
}

# â”€â”€ Auto-detect carrier from container prefix â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CONTAINER_PREFIX_MAP = {
    # CMA CGM prefixes
    "CMAU": "CMA CGM", "CGMU": "CMA CGM", "APHU": "CMA CGM", "APLU": "CMA CGM",
    "CSFU": "CMA CGM", "TCNU": "CMA CGM", "TLLU": "CMA CGM", "SEGU": "CMA CGM",
    "TTNU": "CMA CGM", "ECMU": "CMA CGM", "DVRU": "CMA CGM", "SMUU": "CMA CGM",
    # Hapag-Lloyd
    "HLCU": "Hapag-Lloyd", "HLXU": "Hapag-Lloyd",
    # Maersk
    "MAEU": "Maersk", "MSKU": "Maersk", "MCPU": "Maersk", "MRKU": "Maersk",
    # MSC
    "MSCU": "MSC", "MEDU": "MSC", "MSDU": "MSC",
    # Evergreen
    "EISU": "Evergreen", "EMCU": "Evergreen", "EGHU": "Evergreen",
    # COSCO
    "CCLU": "COSCO", "CBHU": "COSCO", "COSU": "COSCO",
    # ONE
    "ONEY": "ONE", "NYKU": "ONE", "MOFU": "ONE",
    # Yang Ming
    "YMLU": "Yang Ming", "YMTU": "Yang Ming",
    # HMM
    "HMMU": "HMM", "HDMU": "HMM",
    # ZIM
    "ZIMU": "ZIM", "ZCSU": "ZIM",
}

STATUS_MAP = {
    "In Transit": ["in transit","vessel departure","departed","on board","loaded","sailing","at sea","transshipment"],
    "Delivered":  ["delivered","final delivery","gate out","picked up","completed","discharged"],
    "Customs":    ["customs","customs hold","import customs","export customs","inspection","under examination"],
    "Delayed":    ["rollover","delayed","missed connection","vessel change","rolled over","off schedule"],
    "Pending":    ["pending","booking","confirmed","not departed","pre-departure","awaiting"],
}

def get_shipping_line(carrier: str, container_no: str) -> str:
    """Detect carrier from carrier field or container prefix."""
    # Try carrier name first
    if carrier:
        c = carrier.lower().strip()
        for key, val in CARRIER_MAP.items():
            if key in c:
                return val
    # Try container prefix
    if container_no and len(container_no) >= 4:
        prefix = container_no[:4].upper()
        if prefix in CONTAINER_PREFIX_MAP:
            return CONTAINER_PREFIX_MAP[prefix]
    return "OTHERS"

def map_status(raw: str):
    if not raw: return None
    r = raw.lower()
    for status, keywords in STATUS_MAP.items():
        if any(k in r for k in keywords): return status
    return None

def track_and_update(db: Session, shipment) -> dict:
    container_no = (shipment.ref2 or "").strip()
    if not container_no:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}

    shipping_line = get_shipping_line(shipment.carrier or "", container_no)

    try:
        r = requests.get(SHIPSGO_URL, params={
            "authorizationCode": SHIPSGO_TOKEN,
            "containerNo":       container_no,
            "shippingLineCode":  shipping_line,
        }, timeout=20)

        if r.status_code != 200:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"HTTP {r.status_code}", "shipping_line": shipping_line}

        data = r.json()

        # â”€â”€ Parse response fields â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        raw_status = (data.get("containerStatus") or data.get("status") or
                      data.get("lastEvent") or "")
        vessel     = (data.get("vesselName") or data.get("vessel") or
                      data.get("currentVesselName") or "")
        eta_raw    = (data.get("eta") or data.get("estimatedArrival") or
                      data.get("etaFinalDestination") or "")

        # Parse ETA to YYYY-MM-DD
        new_eta = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                new_eta = datetime.strptime(eta_raw[:len(fmt)], fmt).strftime("%Y-%m-%d")
                break
            except: pass

        new_status = map_status(raw_status)
        changed = []

        obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
        if new_status and new_status != obj.status:
            obj.status = new_status; changed.append(f"status â†’ {new_status}")
        if vessel and vessel != obj.vessel:
            obj.vessel = vessel; changed.append(f"vessel â†’ {vessel}")
        if new_eta and new_eta != obj.eta:
            obj.eta = new_eta; changed.append(f"eta â†’ {new_eta}")

        obj.last_tracked = datetime.utcnow().isoformat()
        db.commit()

        return {
            "ref":           shipment.ref,
            "container":     container_no,
            "shipping_line": shipping_line,
            "raw_status":    raw_status,
            "new_status":    new_status,
            "vessel":        vessel,
            "eta":           new_eta,
            "changed":       changed,
            "status":        "updated" if changed else "no_change",
            "raw_response":  data,
        }

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
