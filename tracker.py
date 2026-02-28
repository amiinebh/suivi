import requests, os, time
from datetime import datetime
from sqlalchemy.orm import Session
import models

SHIPSGO_TOKEN = os.getenv("SHIPSGO_TOKEN", "f12e82f3-16c7-4d90-bae4-e63a3aee9c3a")

# â”€â”€ 100% CONFIRMED from official Shipsgo Postman collection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BASE_URL  = "https://api.shipsgo.com/v2"
POST_URL  = f"{BASE_URL}/ocean/shipments"
GET_URL   = f"{BASE_URL}/ocean/shipments"

# Auth header â€” X-Shipsgo-User-Token (confirmed from Postman collection)
def auth_headers():
    return {
        "X-Shipsgo-User-Token": SHIPSGO_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

CONTAINER_PREFIX_MAP = {
    "CMAU": "CMDU", "CGMU": "CMDU", "APHU": "APLU", "APLU": "APLU",
    "CSFU": "CMDU", "TCNU": "CMDU", "TLLU": "CMDU", "SEGU": "CMDU",
    "TTNU": "CMDU", "ECMU": "CMDU", "DVRU": "CMDU", "SMUU": "CMDU",
    "SEKU": "CMDU", "FSCU": "CMDU", "GESU": "CMDU", "REGU": "CMDU",
    "HLCU": "HLCU", "HLXU": "HLCU",
    "MAEU": "MAEU", "MSKU": "MAEU", "MCPU": "MAEU", "MRKU": "MAEU",
    "MSCU": "MSCU", "MEDU": "MSCU", "MSDU": "MSCU", "BMOU": "MSCU",
    "EISU": "EISU", "EMCU": "EISU", "EGHU": "EISU",
    "CCLU": "COSU", "CBHU": "COSU", "COSU": "COSU",
    "ONEY": "ONEY", "NYKU": "ONEY",
    "YMLU": "YMLU", "YMTU": "YMLU",
    "HMMU": "HDMU", "HDMU": "HDMU",
    "ZIMU": "ZIMU", "ZCSU": "ZIMU",
    "PILU": "PILU",
}

STATUS_MAP = {
    "In Transit": ["sailing","in_transit","inprogress","in transit","on board","loaded","departed","at sea","transshipment"],
    "Delivered":  ["delivered","discharged","gate_out","gate out","completed","final"],
    "Customs":    ["customs","inspection"],
    "Delayed":    ["rollover","delayed","rolled"],
    "Pending":    ["pending","booking","inprogress","not departed","awaiting","created"],
}

def get_scac(container_no: str) -> str:
    if container_no and len(container_no) >= 4:
        prefix = container_no[:4].upper()
        return CONTAINER_PREFIX_MAP.get(prefix, "")
    return ""

def map_status(raw: str):
    if not raw: return None
    r = raw.lower().replace("-", "_")
    for status, keywords in STATUS_MAP.items():
        if any(k in r for k in keywords): return status
    return None

def parse_eta(val) -> str:
    if not val: return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try: return datetime.strptime(s[:19], fmt).strftime("%Y-%m-%d")
        except: pass
    try: return s[:10]
    except: pass
    return None

def extract_eta_from_shipment(data: dict) -> str:
    """Extract ETA from Shipsgo v2 ocean shipment response."""
    shipment = data.get("shipment", data)
    route = shipment.get("route") or {}
    if route:
        pod = route.get("port_of_discharge") or {}
        eta = pod.get("date_of_discharge") or pod.get("date_of_discharge_initial")
        if eta: return parse_eta(eta)
    # Check containers list
    containers = shipment.get("containers", [])
    if containers:
        last = containers[-1]
        for field in ["date_of_discharge","eta","estimatedArrival","arrivalDate"]:
            v = last.get(field)
            if v: return parse_eta(v)
    return None

def extract_vessel_from_shipment(data: dict) -> str:
    shipment = data.get("shipment", data)
    containers = shipment.get("containers", [])
    if containers:
        for c in reversed(containers):
            v = c.get("vessel", {})
            if isinstance(v, dict):
                name = v.get("name","")
                if name: return name
            elif isinstance(v, str) and v:
                return v
    return ""

def track_and_update(db: Session, shipment) -> dict:
    container_no = (shipment.ref2 or "").strip()
    if not container_no:
        return {"ref": shipment.ref, "status": "skipped", "reason": "No container number"}

    scac = get_scac(container_no)

    # â”€â”€ STEP 1: POST /ocean/shipments â€” create tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    shipsgo_id = None
    post_debug = ""
    try:
        body = {"container_number": container_no}
        if scac: body["carrier"] = scac
        if shipment.ref: body["reference"] = shipment.ref

        post_r = requests.post(POST_URL, headers=auth_headers(), json=body, timeout=20)
        post_debug = f"POST {post_r.status_code}: {post_r.text[:300]}"

        if post_r.status_code in (200, 201):
            pd = post_r.json()
            s = pd.get("shipment", {})
            shipsgo_id = s.get("id")
        elif post_r.status_code == 409:
            # Already exists â€” extract id
            pd = post_r.json()
            s = pd.get("shipment", {})
            shipsgo_id = s.get("id")
            post_debug += " (already exists)"
        else:
            return {
                "ref": shipment.ref, "status": "error",
                "reason": f"POST {post_r.status_code}: {post_r.text[:300]}",
                "post_debug": post_debug
            }
    except Exception as e:
        return {"ref": shipment.ref, "status": "error",
                "reason": f"POST exception: {str(e)}"}

    time.sleep(3)

    # â”€â”€ STEP 2: GET /ocean/shipments/{id} â€” get tracking details â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not shipsgo_id:
        return {"ref": shipment.ref, "status": "error",
                "reason": "No shipsgo_id returned from POST", "post_debug": post_debug}
    try:
        get_r = requests.get(f"{GET_URL}/{shipsgo_id}", headers=auth_headers(), timeout=20)

        if get_r.status_code != 200:
            return {
                "ref": shipment.ref, "status": "error",
                "reason": f"GET {get_r.status_code}: {get_r.text[:300]}",
                "shipsgo_id": shipsgo_id, "post_debug": post_debug
            }

        data = get_r.json()
        new_eta    = extract_eta_from_shipment(data)
        vessel     = extract_vessel_from_shipment(data)
        s          = data.get("shipment", {})
        raw_status = s.get("status", "")
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
            "scac": scac, "shipsgo_id": shipsgo_id,
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
