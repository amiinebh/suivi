import requests, os
from datetime import datetime
from sqlalchemy.orm import Session
import models

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN", "3fd0583a-9281-4c30-8d9d-ececa0fff69c")
POST_URL = "https://shipsgo.com/api/v1.2/ContainerService/PostContainerInfo"
GET_URL  = "https://shipsgo.com/api/v1.2/ContainerService/GetContainerInfo"

# â”€â”€ Carrier name map â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    "one":         "ONE",
    "yang ming":   "Yang Ming",
    "yangming":    "Yang Ming",
    "hmm":         "HMM",
    "zim":         "ZIM",
    "pil":         "PIL",
}

CONTAINER_PREFIX_MAP = {
    "CMAU": "CMA CGM", "CGMU": "CMA CGM", "APHU": "CMA CGM", "APLU": "CMA CGM",
    "CSFU": "CMA CGM", "TCNU": "CMA CGM", "TLLU": "CMA CGM", "SEGU": "CMA CGM",
    "TTNU": "CMA CGM", "ECMU": "CMA CGM", "DVRU": "CMA CGM", "SMUU": "CMA CGM",
    "HLCU": "Hapag-Lloyd", "HLXU": "Hapag-Lloyd",
    "MAEU": "Maersk", "MSKU": "Maersk", "MCPU": "Maersk", "MRKU": "Maersk",
    "MSCU": "MSC", "MEDU": "MSC", "MSDU": "MSC",
    "EISU": "Evergreen", "EMCU": "Evergreen", "EGHU": "Evergreen",
    "CCLU": "COSCO", "CBHU": "COSCO", "COSU": "COSCO",
    "ONEY": "ONE",  "NYKU": "ONE",
    "YMLU": "Yang Ming", "YMTU": "Yang Ming",
    "HMMU": "HMM",  "HDMU": "HMM",
    "ZIMU": "ZIM",  "ZCSU": "ZIM",
}

STATUS_MAP = {
    "In Transit": ["in transit","vessel departure","departed","on board","loaded",
                   "sailing","at sea","transshipment","vessel arrived"],
    "Delivered":  ["delivered","final delivery","gate out","picked up","completed","discharged"],
    "Customs":    ["customs","customs hold","import customs","export customs","inspection"],
    "Delayed":    ["rollover","delayed","missed connection","vessel change","rolled over"],
    "Pending":    ["pending","booking","confirmed","not departed","pre-departure","awaiting"],
}

def get_shipping_line(carrier: str, container_no: str) -> str:
    if carrier:
        c = carrier.lower().strip()
        for key, val in CARRIER_MAP.items():
            if key in c: return val
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

def parse_eta(eta_raw: str):
    if not eta_raw: return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(eta_raw[:19], fmt[:len(eta_raw[:19])]).strftime("%Y-%m-%d")
        except: pass
    return None

def track_and_update(db: Session, shipment) -> dict:
    container_no  = (shipment.ref2 or "").strip()
    if not container_no:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}

    shipping_line = get_shipping_line(shipment.carrier or "", container_no)

    # â”€â”€ STEP 1: POST to register container with Shipsgo â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        post_resp = requests.post(POST_URL, data={
            "authorizationCode": SHIPSGO_TOKEN,
            "containerNumber":   container_no,
            "shippingLine":      shipping_line,
        }, timeout=20)

        request_id = None
        if post_resp.status_code == 200:
            post_data = post_resp.json()
            # Shipsgo returns requestId or ContainerRequestId
            request_id = (post_data.get("requestId") or
                          post_data.get("ContainerRequestId") or
                          post_data.get("containerRequestId") or
                          str(post_data) if isinstance(post_data, int) else None)
    except Exception as e:
        return {"ref": shipment.ref, "status": "error", "reason": f"POST failed: {str(e)}"}

    # â”€â”€ STEP 2: GET voyage data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        # Can use requestId OR container number directly
        get_params = {"authorizationCode": SHIPSGO_TOKEN}
        if request_id:
            get_params["requestId"] = request_id
        else:
            # fallback: use container number as requestId
            get_params["requestId"] = container_no

        get_resp = requests.get(GET_URL, params=get_params, timeout=20)

        if get_resp.status_code != 200:
            return {"ref": shipment.ref, "status": "error",
                    "reason": f"GET HTTP {get_resp.status_code}",
                    "shipping_line": shipping_line}

        data = get_resp.json()

        # â”€â”€ Parse all possible field names Shipsgo uses â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        raw_status = (data.get("containerStatus") or data.get("status") or
                      data.get("lastEvent") or data.get("ContainerStatus") or "")

        vessel = (data.get("vesselName") or data.get("vessel") or
                  data.get("VesselName") or data.get("currentVesselName") or "")

        # ETA â€” try all known field names
        eta_raw = (data.get("eta") or data.get("ETA") or
                   data.get("estimatedArrival") or data.get("EstimatedArrival") or
                   data.get("etaFinalDestination") or data.get("EtaFinalDestination") or
                   data.get("arrivalDate") or data.get("ArrivalDate") or "")

        new_eta    = parse_eta(str(eta_raw)) if eta_raw else None
        new_status = map_status(str(raw_status))
        changed    = []

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
            "request_id":    request_id,
            "raw_status":    raw_status,
            "new_status":    new_status,
            "vessel":        vessel,
            "eta":           new_eta,
            "changed":       changed,
            "status":        "updated" if changed else "no_change",
            "debug":         data,   # full raw response for debugging
        }

    except Exception as e:
        return {"ref": shipment.ref, "status": "error", "reason": f"GET failed: {str(e)}"}


def run_auto_tracking(db: Session) -> list:
    active = db.query(models.Shipment).filter(
        models.Shipment.mode == "Ocean",
        models.Shipment.status.notin_(["Delivered"]),
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    return [track_and_update(db, s) for s in active]
