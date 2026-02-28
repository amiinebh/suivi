import requests, os, time
from datetime import datetime
from sqlalchemy.orm import Session
import models

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN", "f12e82f3-16c7-4d90-bae4-e63a3aee9c3a")

# â”€â”€ Correct Shipsgo v2 API endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
POST_URL = "https://shipsgo.com/api/v2/container"
GET_URL  = "https://shipsgo.com/api/v2/container"

CONTAINER_PREFIX_MAP = {
    "CMAU": "CMA CGM", "CGMU": "CMA CGM", "APHU": "CMA CGM", "APLU": "CMA CGM",
    "CSFU": "CMA CGM", "TCNU": "CMA CGM", "TLLU": "CMA CGM", "SEGU": "CMA CGM",
    "TTNU": "CMA CGM", "ECMU": "CMA CGM", "DVRU": "CMA CGM", "SMUU": "CMA CGM",
    "SEKU": "CMA CGM", "FSCU": "CMA CGM", "GESU": "CMA CGM", "REGU": "CMA CGM",
    "HLCU": "Hapag-Lloyd", "HLXU": "Hapag-Lloyd",
    "MAEU": "Maersk", "MSKU": "Maersk", "MCPU": "Maersk", "MRKU": "Maersk",
    "MSCU": "MSC", "MEDU": "MSC", "MSDU": "MSC", "BMOU": "MSC",
    "EISU": "Evergreen", "EMCU": "Evergreen", "EGHU": "Evergreen",
    "CCLU": "COSCO", "CBHU": "COSCO", "COSU": "COSCO",
    "ONEY": "ONE", "NYKU": "ONE",
    "YMLU": "Yang Ming", "YMTU": "Yang Ming",
    "HMMU": "HMM", "HDMU": "HMM",
    "ZIMU": "ZIM", "ZCSU": "ZIM",
    "PILU": "PIL",
}

CARRIER_NAME_MAP = {
    "cma": "CMA CGM", "cma cgm": "CMA CGM", "cmacgm": "CMA CGM",
    "hapag": "Hapag-Lloyd", "hapag-lloyd": "Hapag-Lloyd",
    "maersk": "Maersk", "msc": "MSC", "evergreen": "Evergreen",
    "cosco": "COSCO", "one": "ONE", "yang ming": "Yang Ming",
    "hmm": "HMM", "zim": "ZIM", "pil": "PIL",
}

STATUS_MAP = {
    "In Transit": ["in transit","vessel departure","departed","on board","loaded",
                   "sailing","at sea","transshipment","vessel arrived","arrival"],
    "Delivered":  ["delivered","final delivery","gate out","picked up","completed","discharged"],
    "Customs":    ["customs","customs hold","import customs","export customs","inspection"],
    "Delayed":    ["rollover","delayed","missed connection","vessel change","rolled over"],
    "Pending":    ["pending","booking","confirmed","not departed","pre-departure","awaiting"],
}

def get_shipping_line(carrier: str, container_no: str) -> str:
    if carrier:
        c = carrier.lower().strip()
        for key, val in CARRIER_NAME_MAP.items():
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

def parse_eta(val) -> str:
    if not val: return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try: return datetime.strptime(s[:len(fmt)], fmt).strftime("%Y-%m-%d")
        except: pass
    try: return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except: pass
    return None

def extract_eta(data: dict) -> str:
    eta_fields = ["eta","ETA","Eta","estimatedArrival","EstimatedArrival",
                  "etaFinalDestination","EtaFinalDestination","arrivalDate",
                  "ArrivalDate","estimatedTimeArrival","etaDate","finalEta","portEta"]
    for field in eta_fields:
        val = data.get(field)
        if val:
            parsed = parse_eta(val)
            if parsed: return parsed
    for key in ["routeList","RouteList","legs","Legs","containers","Containers"]:
        nested = data.get(key)
        if isinstance(nested, list) and nested:
            last = nested[-1]
            if isinstance(last, dict):
                for field in eta_fields:
                    val = last.get(field)
                    if val:
                        parsed = parse_eta(val)
                        if parsed: return parsed
    return None

def extract_vessel(data: dict) -> str:
    for f in ["vesselName","VesselName","vessel","Vessel","currentVesselName","shipName"]:
        v = data.get(f)
        if v and str(v).strip(): return str(v).strip()
    return ""

def track_and_update(db: Session, shipment) -> dict:
    container_no = (shipment.ref2 or "").strip()
    if not container_no:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}

    shipping_line = get_shipping_line(shipment.carrier or "", container_no)
    headers = {
        "Authorization": f"Bearer {SHIPSGO_TOKEN}",
        "Content-Type": "application/json",
    }

    # â”€â”€ STEP 1: POST to create tracking request â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    request_id = None
    post_debug = ""
    try:
        post_r = requests.post(
            POST_URL,
            headers=headers,
            json={
                "containerNumber": container_no,
                "shippingLine":    shipping_line,
            },
            timeout=20
        )
        post_debug = f"POST {post_r.status_code}: {post_r.text[:200]}"
        if post_r.status_code in (200, 201):
            try:
                pd = post_r.json()
                if isinstance(pd, int): request_id = pd
                elif isinstance(pd, dict):
                    request_id = (pd.get("id") or pd.get("requestId") or
                                  pd.get("ContainerRequestId") or pd.get("containerRequestId"))
                elif isinstance(pd, str) and pd.strip().lstrip("-").isdigit():
                    request_id = int(pd.strip())
            except: pass
    except Exception as e:
        post_debug = f"POST exception: {str(e)}"

    time.sleep(3)

    # â”€â”€ STEP 2: GET tracking data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        get_params = {}
        if request_id:
            get_url = f"{GET_URL}/{request_id}"
        else:
            get_url = GET_URL
            get_params["containerNumber"] = container_no

        get_r = requests.get(get_url, headers=headers, params=get_params, timeout=20)

        if get_r.status_code != 200:
            return {
                "ref": shipment.ref, "status": "error",
                "reason": f"GET HTTP {get_r.status_code}: {get_r.text[:300]}",
                "shipping_line": shipping_line, "request_id": request_id,
                "post_debug": post_debug,
            }

        data = get_r.json()
        new_eta    = extract_eta(data)
        vessel     = extract_vessel(data)
        raw_status = (data.get("containerStatus") or data.get("status") or
                      data.get("ContainerStatus") or data.get("lastEvent") or "")
        new_status = map_status(str(raw_status))
        changed    = []

        obj = db.query(models.Shipment).filter(models.Shipment.id == shipment.id).first()
        if new_status and new_status != obj.status:
            obj.status = new_status; changed.append(f"status â†’ {new_status}")
        if vessel and vessel != obj.vessel:
            obj.vessel = vessel; changed.append(f"vessel â†’ {vessel}")
        if new_eta and new_eta != obj.eta:
            obj.eta = new_eta; changed.append(f"ETA â†’ {new_eta}")

        obj.last_tracked = datetime.utcnow().isoformat()
        db.commit()

        return {
            "ref": shipment.ref, "container": container_no,
            "shipping_line": shipping_line, "request_id": request_id,
            "post_debug": post_debug,
            "raw_status": raw_status, "new_status": new_status,
            "vessel": vessel, "eta": new_eta,
            "changed": changed,
            "status": "updated" if changed else "no_change",
            "debug": data,
        }

    except Exception as e:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"GET exception: {str(e)}", "post_debug": post_debug}


def run_auto_tracking(db: Session) -> list:
    active = db.query(models.Shipment).filter(
        models.Shipment.mode == "Ocean",
        models.Shipment.status.notin_(["Delivered"]),
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    return [track_and_update(db, s) for s in active]
