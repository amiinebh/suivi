from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File
from auth import get_current_user, require_admin, hash_password, verify_password, create_token
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
import models, schemas, crud, export
from database import SessionLocal, engine
import os, logging, io, re
from datetime import date, datetime

logging.basicConfig(level=logging.INFO)
models.Base.metadata.create_all(bind=engine)
from database import run_migrations
run_migrations()

app = FastAPI(title="FreightTrack Pro")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ─────────────────────────────────────────────
# NAME NORMALISATION MAPS
# ─────────────────────────────────────────────
CARRIER_MAP = {
    "MSK": "Maersk", "MAERSK": "Maersk", "MAERSK LINE": "Maersk", "MAERSKLINE": "Maersk",
    "CMA": "CMA-CGM", "CMA CGM": "CMA-CGM", "CMACGM": "CMA-CGM", "CMA-CGM": "CMA-CGM",
    "MSC": "MSC", "MEDITERRANEAN SHIPPING": "MSC",
    "HPL": "Hapag-Lloyd", "HAPAG": "Hapag-Lloyd", "HAPAG LLOYD": "Hapag-Lloyd", "HAPAG-LLOYD": "Hapag-Lloyd",
    "EVE": "Evergreen", "EVERGREEN": "Evergreen", "EMC": "Evergreen",
    "COS": "COSCO", "COSCO": "COSCO",
    "ONE": "ONE", "OCEAN NETWORK EXPRESS": "ONE",
    "YML": "Yang Ming", "YANG MING": "Yang Ming", "YANGMING": "Yang Ming",
    "HMM": "HMM", "HYUNDAI": "HMM",
    "PIL": "PIL", "PACIFIC INTERNATIONAL LINES": "PIL",
    "ZIM": "ZIM",
    "ARKAS": "Arkas", "MARFRET": "Marfret",
    "COMANAV": "Comanav", "IMTC": "IMTC",
}

CLIENT_MAP = {
    "COPAG": "COPAG", "Copag": "COPAG", "copag": "COPAG",
}

def normalize_carrier(name: str) -> str:
    if not name: return name
    key = re.sub(r"[^A-Z0-9 ]", " ", name.strip().upper()).strip()
    # Try full key first, then collapse spaces
    if key in CARRIER_MAP: return CARRIER_MAP[key]
    key2 = re.sub(r"\s+", "", key)
    for k, v in CARRIER_MAP.items():
        if re.sub(r"[^A-Z0-9]", "", k) == key2:
            return v
    return name.strip().title()

def normalize_client(name: str) -> str:
    if not name: return name
    upper = name.strip().upper()
    if upper in CLIENT_MAP: return CLIENT_MAP[upper]
    # Title-case as fallback canonical form
    return name.strip().title()

def normalize_mode(mode: str) -> str:
    if not mode: return "Ocean"
    m = mode.strip().lower()
    if m in ("road", "ftl", "truck", "road (ftl)"): return "Road"
    return "Ocean"

def normalize_direction(d: str) -> str:
    if not d: return None
    d = d.strip().lower()
    if d in ("export", "exp", "x"): return "Export"
    if d in ("import", "imp", "m"): return "Import"
    return d.capitalize()

def compute_status(etd, eta, has_container: bool) -> str:
    """
    Compute auto-status from dates and container presence.
    - No container data → Pending
    - today < ETD → Confirmed
    - ETD <= today < ETA → Sailing
    - today >= ETA → Arrived
    """
    if not has_container:
        return "Pending"
    today = date.today()
    def parse(d):
        if not d: return None
        try: return date.fromisoformat(str(d).split("T")[0])
        except: return None
    etd_d = parse(etd)
    eta_d = parse(eta)
    if etd_d and today < etd_d:
        return "Confirmed"
    if etd_d and eta_d and etd_d <= today < eta_d:
        return "Sailing"
    if eta_d and today >= eta_d:
        return "Arrived"
    if etd_d and today >= etd_d:
        return "Sailing"
    return "Confirmed"

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.get("/")
def root():
    from fastapi.responses import HTMLResponse
    import pathlib
    html_path = pathlib.Path("static/index.html")
    content = html_path.read_text(encoding="utf-8") if html_path.exists() else "<h1>Loading...</h1>"
    return HTMLResponse(content=content, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache", "Expires": "0", "X-Version": "v27"
    })

@app.get("/track/{ref}")
def client_portal(ref: str):
    return FileResponse("static/portal/index.html")

@app.get("/api/portal/{ref}")
def portal_data(ref: str, db: Session = Depends(get_db)):
    s = crud.get_shipment(db, ref)
    if not s: raise HTTPException(404, "Shipment not found")
    return {
        "ref": s.ref, "ref2": s.ref2, "mode": s.mode, "carrier": s.carrier,
        "vessel": s.vessel, "pol": s.pol, "pod": s.pod, "etd": s.etd, "eta": s.eta,
        "status": s.status, "client": s.client, "lasttracked": s.lasttracked,
        "events": [{"timestamp": e.timestamp, "location": e.location,
                    "description": e.description, "status": e.status}
                   for e in sorted(s.events, key=lambda x: x.timestamp, reverse=True)]
    }

# ── Shipments ──────────────────────────────────
@app.get("/api/shipments", response_model=list[schemas.ShipmentOut])
def list_shipments(q: str = "", search: str = "", status: str = "", mode: str = "",
                   db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_shipments(db, q or search, status, mode)

@app.post("/api/shipments", response_model=schemas.ShipmentOut)
async def create_shipment(request: Request, db: Session = Depends(get_db),
                          current=Depends(get_current_user)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    if "quotationnumber" in body and "quotation_number" not in body:
        body["quotation_number"] = body.pop("quotationnumber")
    ref = (body.get("ref") or "").strip()
    if not ref: raise HTTPException(400, "Reference is required")
    if crud.get_shipment(db, ref): raise HTTPException(400, "Reference already exists")
    allowed = set(schemas.ShipmentCreate.model_fields.keys())
    sdata = {}
    for k, v in body.items():
        if k not in allowed: continue
        sdata[k] = v.strip() if isinstance(v, str) and v.strip() != "" else (None if isinstance(v, str) else v)
    sdata["ref"] = ref
    # Normalise
    if sdata.get("carrier"): sdata["carrier"] = normalize_carrier(sdata["carrier"])
    if sdata.get("client"): sdata["client"] = normalize_client(sdata["client"])
    if sdata.get("mode"): sdata["mode"] = normalize_mode(sdata["mode"])
    if sdata.get("direction"): sdata["direction"] = normalize_direction(sdata["direction"])
    sdata.setdefault("mode", "Ocean")
    sdata.setdefault("status", "Confirmed")
    try:
        s = schemas.ShipmentCreate(**sdata)
        return crud.create_shipment(db, s)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"Failed to create shipment: {str(e)}")

# ── Bulk Import (JSON) ─────────────────────────
@app.post("/api/shipments/bulk")
async def bulk_import_shipments(request: Request, db: Session = Depends(get_db),
                                 current=Depends(get_current_user)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    rows = body.get("shipments", [])
    if not rows: raise HTTPException(400, "No shipments provided")
    allowed = set(schemas.ShipmentCreate.model_fields.keys())
    created_count = 0
    skipped = []
    for row in rows:
        ref = str(row.get("ref", "")).strip()
        if not ref:
            skipped.append({"ref": None, "reason": "Missing ref"}); continue
        if crud.get_shipment(db, ref):
            skipped.append({"ref": ref, "reason": "Already exists"}); continue
        sdata = {}
        for k, v in row.items():
            if k not in allowed: continue
            sdata[k] = v.strip() if isinstance(v, str) and v.strip() != "" else (None if isinstance(v, str) else v)
        sdata["ref"] = ref
        if sdata.get("carrier"): sdata["carrier"] = normalize_carrier(sdata["carrier"])
        if sdata.get("client"): sdata["client"] = normalize_client(sdata["client"])
        if sdata.get("mode"): sdata["mode"] = normalize_mode(sdata["mode"])
        if sdata.get("direction"): sdata["direction"] = normalize_direction(sdata["direction"])
        sdata.setdefault("mode", "Ocean")
        sdata.setdefault("status", "Confirmed")
        try:
            s = schemas.ShipmentCreate(**sdata)
            crud.create_shipment(db, s)
            created_count += 1
        except Exception as e:
            skipped.append({"ref": ref, "reason": str(e)})
    return {"created": created_count, "skipped": skipped, "total": len(rows)}

@app.get("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def get_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.put("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
async def update_shipment(sid: int, request: Request, db: Session = Depends(get_db),
                          current=Depends(get_current_user)):
    body = await request.json()
    allowed = set(schemas.ShipmentUpdate.model_fields.keys())
    filtered = {k: (v if v != "" else None) for k, v in body.items() if k in allowed}
    if filtered.get("carrier"): filtered["carrier"] = normalize_carrier(filtered["carrier"])
    if filtered.get("client"): filtered["client"] = normalize_client(filtered["client"])
    if filtered.get("mode"): filtered["mode"] = normalize_mode(filtered["mode"])
    if filtered.get("direction"): filtered["direction"] = normalize_direction(filtered["direction"])
    data = schemas.ShipmentUpdate(**filtered)
    s = crud.update_shipment(db, sid, data)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    crud.delete_shipment(db, sid)
    return {"ok": True}

@app.patch("/api/shipments/{sid}/status")
async def update_status(sid: int, request: Request, db: Session = Depends(get_db),
                        current=Depends(get_current_user)):
    body = await request.json()
    status = body.get("status", "").strip()
    if not status: raise HTTPException(400, "Status required")
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    s.status = status
    db.commit(); db.refresh(s)
    return s

# ── Comments ───────────────────────────────────
@app.post("/api/shipments/{sid}/comments", response_model=schemas.CommentOut)
def add_comment(sid: int, data: schemas.CommentCreate, db: Session = Depends(get_db),
                current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return crud.add_comment(db, sid, data)

# ── Export XLSX ────────────────────────────────
@app.get("/api/export/xlsx")
def export_xlsx(search: str = "", status: str = "", mode: str = "",
                db: Session = Depends(get_db), current=Depends(get_current_user)):
    ships = crud.get_shipments(db, search, status, mode)
    data = export.export_shipments_xlsx(ships)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=shipments.xlsx"})

# ── KPIs & Stats ───────────────────────────────
@app.get("/api/kpis")
def get_kpis(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_kpis(db)

@app.get("/api/stats")
def stats(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_stats(db)

# ── Full KPI Report ────────────────────────────
@app.get("/api/kpi-report")
def kpi_report(db: Session = Depends(get_db), current=Depends(get_current_user)):
    """
    Rich KPI report with:
    - per-client shipment count + TEU, split by direction
    - top POL, top POD, top routing (POL->POD)
    - by_carrier, by_status, by_mode, by_direction
    - auto-status computed server-side for accuracy
    """
    from collections import defaultdict
    today = date.today()

    all_ships = crud.get_shipments(db, "", "", "")

    def has_container(s):
        return bool(getattr(s, "containers", None) and len(s.containers) > 0) or bool(getattr(s, "teu", None) and s.teu)

    def auto_status(s):
        return compute_status(s.etd, s.eta, has_container(s))

    # Counters
    by_client_exp = defaultdict(lambda: {"shipments": 0, "teu": 0})
    by_client_imp = defaultdict(lambda: {"shipments": 0, "teu": 0})
    by_carrier    = defaultdict(int)
    by_carrier_exp= defaultdict(int)
    by_carrier_imp= defaultdict(int)
    by_status     = defaultdict(int)
    by_mode       = defaultdict(int)
    by_pol        = defaultdict(int)
    by_pol_exp    = defaultdict(int)
    by_pol_imp    = defaultdict(int)
    by_pod        = defaultdict(int)
    by_pod_exp    = defaultdict(int)
    by_pod_imp    = defaultdict(int)
    by_routing    = defaultdict(int)
    by_routing_exp= defaultdict(int)
    by_routing_imp= defaultdict(int)
    by_direction  = {"Export": 0, "Import": 0, "Unknown": 0}
    total_teu     = 0
    monthly       = defaultdict(int)

    for s in all_ships:
        cn = normalize_client(s.client or "Unknown")
        car = normalize_carrier(s.carrier or "Unknown")
        st  = auto_status(s)
        mod = normalize_mode(s.mode or "Ocean")
        teu = s.teu or 0
        total_teu += teu

        direction = normalize_direction(s.direction or "") or "Unknown"
        if direction not in ("Export", "Import"):
            direction = "Unknown"
        by_direction[direction] = by_direction.get(direction, 0) + 1

        if direction == "Export":
            by_client_exp[cn]["shipments"] += 1
            by_client_exp[cn]["teu"] += teu
        elif direction == "Import":
            by_client_imp[cn]["shipments"] += 1
            by_client_imp[cn]["teu"] += teu
        else:
            # Count in both aggregate but not split
            by_client_exp[cn]["shipments"] += 0  # keep key present
            by_client_imp[cn]["shipments"] += 0

        by_carrier[car] += 1
        if direction=="Export": by_carrier_exp[car]+=1
        elif direction=="Import": by_carrier_imp[car]+=1
        by_status[st] += 1
        by_mode[mod] += 1
        if s.pol:
            by_pol[s.pol.upper()]+=1
            if direction=="Export": by_pol_exp[s.pol.upper()]+=1
            elif direction=="Import": by_pol_imp[s.pol.upper()]+=1
        if s.pod:
            by_pod[s.pod.upper()]+=1
            if direction=="Export": by_pod_exp[s.pod.upper()]+=1
            elif direction=="Import": by_pod_imp[s.pod.upper()]+=1
        if s.pol and s.pod:
            route=f"{s.pol.upper()} → {s.pod.upper()}"
            by_routing[route]+=1
            if direction=="Export": by_routing_exp[route]+=1
            elif direction=="Import": by_routing_imp[route]+=1

        # Monthly (by ETD)
        if s.etd:
            try:
                m = str(s.etd)[:7]  # YYYY-MM
                monthly[m] += 1
            except: pass

    def top(d, n=10):
        return sorted([{"name": k, "count": v} for k, v in d.items()], key=lambda x: -x["count"])[:n]

    def top_str(d, n=10):
        return sorted([{"name": k, "count": v} for k, v in d.items()], key=lambda x: -x["count"])[:n]

    # All-clients combined (for overall view)
    all_clients = defaultdict(lambda: {"shipments": 0, "teu": 0})
    for s in all_ships:
        cn = normalize_client(s.client or "Unknown")
        all_clients[cn]["shipments"] += 1
        all_clients[cn]["teu"] += (s.teu or 0)

    # Build monthly list sorted
    monthly_list = sorted([{"month": k, "count": v} for k, v in monthly.items()], key=lambda x: x["month"])

    return {
        "total": len(all_ships),
        "total_teu": total_teu,
        "by_direction": by_direction,
        "by_status": dict(by_status),
        "by_mode": dict(by_mode),
        "by_carrier": top(by_carrier, 10),
        "by_carrier_export": top(by_carrier_exp,10),
        "by_carrier_import": top(by_carrier_imp,10),
        "by_client_all": sorted(
            [{"name": k, "shipments": v["shipments"], "teu": v["teu"]} for k, v in all_clients.items()],
            key=lambda x: -x["shipments"]
        )[:15],
        "by_client_export": sorted(
            [{"name": k, "shipments": v["shipments"], "teu": v["teu"]} for k, v in by_client_exp.items() if v["shipments"] > 0],
            key=lambda x: -x["shipments"]
        )[:15],
        "by_client_import": sorted(
            [{"name": k, "shipments": v["shipments"], "teu": v["teu"]} for k, v in by_client_imp.items() if v["shipments"] > 0],
            key=lambda x: -x["shipments"]
        )[:15],
        "top_pol": top_str(by_pol,8),
        "top_pol_export": top_str(by_pol_exp,8),
        "top_pol_import": top_str(by_pol_imp,8),
        "top_pod": top_str(by_pod,8),
        "top_pod_export": top_str(by_pod_exp,8),
        "top_pod_import": top_str(by_pod_imp,8),
        "top_routing": sorted([{"route":k,"count":v} for k,v in by_routing.items()],key=lambda x:-x["count"])[:10],
        "top_routing_export": sorted([{"route":k,"count":v} for k,v in by_routing_exp.items()],key=lambda x:-x["count"])[:10],
        "top_routing_import": sorted([{"route":k,"count":v} for k,v in by_routing_imp.items()],key=lambda x:-x["count"])[:10],
        "monthly": monthly_list,
        # Legacy fields for backward compat
        "by_client": top(by_carrier, 10),  # kept for old frontend
        "top_routes": [{"route": k, "count": v} for k, v in sorted(by_routing.items(), key=lambda x: -x[1])[:10]],
        "overdue": [],
        "on_time_rate": 0,
        "delay_rate": 0,
        "avg_transit": None,
    }

# ── Health ─────────────────────────────────────
@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        from sqlalchemy import text; db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

# ── Containers ─────────────────────────────────
@app.get("/api/shipments/{sid}/containers")
def get_containers(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Shipment not found")
    return s.containers

@app.post("/api/shipments/{sid}/containers")
def add_container(sid: int, data: dict, db: Session = Depends(get_db),
                  current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Shipment not found")
    from models import Container
    cont = Container(shipment_id=sid, container_no=data.get("container_no"),
                     seal_no=data.get("seal_no"), size_type=data.get("size_type"),
                     weight=data.get("weight"))
    db.add(cont); db.commit(); db.refresh(cont)
    return cont

@app.delete("/api/containers/{cid}")
def delete_container(cid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    from models import Container
    cont = db.query(Container).filter(Container.id == cid).first()
    if not cont: raise HTTPException(404, "Container not found")
    db.delete(cont); db.commit()
    return {"ok": True}

# ── Email ──────────────────────────────────────
@app.post("/api/shipments/{sid}/send-email")
async def send_email(sid: int, request: Request, db: Session = Depends(get_db),
                     current=Depends(get_current_user)):
    body = await request.json()
    subject = body.get("subject", "").strip()
    email_body = body.get("body", "").strip()
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Shipment not found")
    if not s.clientemail: raise HTTPException(400, "No client email on this shipment")
    if not subject or not email_body: raise HTTPException(400, "Subject and body required")
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("FROM_EMAIL", smtp_user)
    if not smtp_host or not smtp_user: raise HTTPException(500, "SMTP not configured")
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject; msg["From"] = from_email; msg["To"] = s.clientemail
        msg.attach(MIMEText(email_body, "plain"))
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(); server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, s.clientemail, msg.as_string())
        try:
            sent_by = current.get("name", "System") if isinstance(current, dict) else "System"
            crud.log_email(db, sid, subject, s.clientemail, sent_by)
        except: pass
        return {"ok": True, "sent_to": s.clientemail}
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"Email send failed: {str(e)}")

@app.get("/api/shipments/{sid}/email-log")
def email_log(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    try: return crud.get_email_log(db, sid)
    except: return []

# ── Bulk Import (file upload) ──────────────────
@app.post("/api/shipments/bulk-import")
async def bulk_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                      current=Depends(get_current_user)):
    import openpyxl
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active

    def norm_header(value):
        raw = str(value or "").strip().lower()
        key = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
        aliases = {
            "reference": "ref", "ref_no": "ref", "reference_no": "ref",
            "booking": "booking_no", "bookingno": "booking_no", "booking_number": "booking_no",
            "clientemail": "client_email", "email": "client_email",
            "quotation": "quotation_number", "quotationno": "quotation_number",
            "lasttracked": "last_tracked", "createdat": "created_at",
            "containers": "container", "truck_plate": "container", "plate": "container",
            "nb_teu": "teu", "teus": "teu",
            "direction": "direction", "flow": "direction", "type": "direction",
        }
        return aliases.get(key, key)

    headers = [norm_header(c.value) for c in next(ws.iter_rows(min_row=1, max_row=1))]

    def parse_date(val):
        if not val: return None
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"]:
            try: return datetime.strptime(str(val).strip(), fmt).strftime("%Y-%m-%d")
            except: pass
        return None

    created, skipped, errors = [], [], []

    updated = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        rd = {headers[i]: (str(v).strip() if v is not None else "")
              for i, v in enumerate(row) if i < len(headers)}
        ref = rd.get("ref", "").strip()
        if not ref: continue
        try:
            teu_raw = rd.get("teu", "")
            try: teu = int(float(teu_raw)) if teu_raw else None
            except: teu = None

            raw_status = rd.get("status", "").strip()
            carrier_norm = normalize_carrier(rd.get("carrier", ""))
            client_norm  = normalize_client(rd.get("client", ""))
            mode_norm    = normalize_mode(rd.get("mode", "Ocean"))
            dir_norm     = normalize_direction(rd.get("direction", ""))

            # Auto-status: check container field from excel
            container_val = rd.get("container", "").strip()
            has_cont = bool(container_val) or bool(teu)

            auto_st = compute_status(
                parse_date(rd.get("etd")),
                parse_date(rd.get("eta")),
                has_cont
            )

            existing = db.query(models.Shipment).filter(models.Shipment.ref == ref).first()
            if existing:
                if rd.get("ref2"):         existing.ref2         = rd["ref2"]
                if rd.get("booking_no"):   existing.booking_no   = rd["booking_no"]
                if mode_norm:              existing.mode         = mode_norm
                if carrier_norm:           existing.carrier      = carrier_norm
                if rd.get("shipper"):      existing.shipper      = rd["shipper"]
                if rd.get("consignee"):    existing.consignee    = rd["consignee"]
                if client_norm:            existing.client       = client_norm
                if rd.get("client_email"): existing.client_email = rd["client_email"]
                if rd.get("pol"):          existing.pol          = rd["pol"]
                if rd.get("pod"):          existing.pod          = rd["pod"]
                if rd.get("etd"):          existing.etd          = parse_date(rd["etd"])
                if rd.get("eta"):          existing.eta          = parse_date(rd["eta"])
                if rd.get("incoterm"):     existing.incoterm     = rd["incoterm"]
                if teu is not None:        existing.teu          = teu
                if dir_norm:               existing.direction    = dir_norm
                existing.status = auto_st
                db.commit()
                if container_val:
                    from models import Container as Cont
                    db.query(Cont).filter(Cont.shipment_id == existing.id).delete()
                    for cno in re.split(r"[,;/\\|]", container_val):
                        cno = cno.strip()
                        if cno: db.add(Cont(shipment_id=existing.id, container_no=cno))
                    db.commit()
                updated.append(ref)
                continue
            s = models.Shipment(
                ref=ref,
                ref2=rd.get("ref2", "") or None,
                booking_no=rd.get("booking_no", "") or None,
                mode=mode_norm,
                carrier=carrier_norm or None,
                shipper=rd.get("shipper", "") or None,
                consignee=rd.get("consignee", "") or None,
                client=client_norm or None,
                client_email=rd.get("client_email", "") or None,
                pol=rd.get("pol", "") or None,
                pod=rd.get("pod", "") or None,
                etd=parse_date(rd.get("etd")),
                eta=parse_date(rd.get("eta")),
                status=auto_st,
                incoterm=rd.get("incoterm", "") or None,
                vessel=rd.get("vessel", "") or None,
                voyage=rd.get("voyage", "") or None,
                teu=teu,
                note=rd.get("note", "") or None,
                quotation_number=rd.get("quotation_number", "") or None,
                direction=dir_norm,
                created_at=datetime.utcnow().isoformat()
            )
            db.add(s)
            db.commit()

            # If container column has value, create Container record
            if container_val:
                from models import Container as Cont
                for cno in re.split(r"[,;/\\|]", container_val):
                    cno = cno.strip()
                    if cno:
                        db.add(Cont(shipment_id=s.id, container_no=cno))
                db.commit()

            created.append(ref)
        except Exception as e:
            errors.append({"ref": ref, "error": str(e)})

    return {"created": len(created), "updated": len(updated), "skipped": len(skipped), "errors": errors}

# ── Seed Samples ───────────────────────────────
@app.post("/api/seed-samples")
def seed_samples(db: Session = Depends(get_db)):
    allowed = {c.name for c in models.Shipment.__table__.columns}
    samples = [
        {"ref":"FT-2026-001","mode":"Ocean","carrier":"MSC","client":"COPAG","pol":"Shanghai","pod":"Casablanca","etd":"2026-01-05","eta":"2026-02-10","status":"Arrived","incoterm":"FOB","vessel":"MSC DIANA","teu":2,"direction":"Import"},
        {"ref":"FT-2026-002","mode":"Ocean","carrier":"CMA-CGM","client":"Atlas Pharma","pol":"Casablanca","pod":"Marseille","etd":"2026-01-12","eta":"2026-01-18","status":"Arrived","incoterm":"CIF","teu":4,"direction":"Export"},
        {"ref":"FT-2026-003","mode":"Road","carrier":"CTM","client":"COPAG","pol":"Casablanca","pod":"Madrid","etd":"2026-01-20","eta":"2026-01-22","status":"Arrived","incoterm":"DAP","direction":"Export"},
        {"ref":"FT-2026-004","mode":"Ocean","carrier":"Maersk","client":"Atlas Pharma","pol":"Casablanca","pod":"Hamburg","etd":"2026-01-25","eta":"2026-02-15","status":"Arrived","incoterm":"FOB","vessel":"MAERSK ELBA","teu":6,"direction":"Export"},
        {"ref":"FT-2026-005","mode":"Ocean","carrier":"MSC","client":"Casa Ceramics","pol":"Valencia","pod":"Casablanca","etd":"2026-02-01","eta":"2026-02-08","status":"Arrived","incoterm":"CFR","vessel":"MSC ANNA","teu":2,"direction":"Import"},
        {"ref":"FT-2026-006","mode":"Ocean","carrier":"Hapag-Lloyd","client":"Maroc Textiles","pol":"Casablanca","pod":"Antwerp","etd":"2026-02-18","eta":"2026-03-01","status":"Arrived","incoterm":"CIF","vessel":"HAPAG BERLIN","teu":4,"direction":"Export"},
        {"ref":"FT-2026-007","mode":"Ocean","carrier":"MSC","client":"Maroc Textiles","pol":"Chennai","pod":"Casablanca","etd":"2026-02-20","eta":"2026-03-25","status":"Arrived","incoterm":"FOB","vessel":"MSC ROMA","teu":3,"direction":"Import"},
        {"ref":"FT-2026-008","mode":"Ocean","carrier":"CMA-CGM","client":"Casa Ceramics","pol":"Casablanca","pod":"Rotterdam","etd":"2026-03-03","eta":"2026-03-10","status":"Arrived","incoterm":"CFR","teu":2,"direction":"Export"},
        {"ref":"FT-2026-009","mode":"Ocean","carrier":"MSC","client":"COPAG","pol":"Ningbo","pod":"Casablanca","etd":"2026-03-06","eta":"2026-04-15","status":"Sailing","incoterm":"EXW","vessel":"MSC FIAMMETTA","teu":5,"direction":"Import"},
        {"ref":"FT-2026-010","mode":"Road","carrier":"ONCF","client":"Atlas Pharma","pol":"Rabat","pod":"Lyon","etd":"2026-03-20","eta":"2026-03-23","status":"Confirmed","incoterm":"DAP","direction":"Export"},
        {"ref":"FT-2026-011","mode":"Ocean","carrier":"Maersk","client":"Maroc Textiles","pol":"Casablanca","pod":"Hamburg","etd":"2026-04-10","eta":"2026-05-01","status":"Confirmed","incoterm":"FOB","vessel":"MAERSK MILAN","teu":4,"direction":"Export"},
        {"ref":"FT-2026-012","mode":"Ocean","carrier":"Evergreen","client":"Casa Ceramics","pol":"Kaohsiung","pod":"Casablanca","etd":"2026-04-15","eta":"2026-05-20","status":"Confirmed","incoterm":"CIF","teu":2,"direction":"Import"},
    ]
    added = 0
    for s in samples:
        if not db.query(models.Shipment).filter(models.Shipment.ref == s["ref"]).first():
            db.add(models.Shipment(**{k: v for k, v in s.items() if k in allowed}))
            added += 1
    db.commit()
    return {"added": added, "message": f"Seeded {added} sample shipments"}

# ── PDF ────────────────────────────────────────
@app.get("/api/shipments/{sid}/pdf")
def shipment_pdf(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    import pdfexport
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Shipment not found")
    return Response(content=pdfexport.generate_shipment_pdf(s), media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={s.ref}.pdf"})

@app.get("/api/dashboard/pdf")
def dashboard_pdf(db: Session = Depends(get_db), current=Depends(get_current_user)):
    import pdfexport
    pdf_bytes = pdfexport.generate_dashboard_pdf(crud.get_stats(db), crud.get_shipments(db,"","",""))
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=dashboard_{datetime.now().strftime('%Y%m%d')}.pdf"})

# ── Auth & Users ───────────────────────────────
def ensure_admin(db):
    from models import User
    if not db.query(User).filter(User.role == "admin").first():
        db.add(User(
            email=os.getenv("ADMIN_EMAIL", "admin@freighttrack.com"),
            name="Admin", role="admin",
            hashedpw=hash_password(os.getenv("ADMIN_PASSWORD", "Admin1234!")),
            isactive=True
        ))
        db.commit()
        print("Default admin created")

@app.on_event("startup")
def on_startup():
    from database import Base, engine, SessionLocal, run_migrations
    Base.metadata.create_all(bind=engine)
    run_migrations()
    db = SessionLocal()
    try: ensure_admin(db)
    except Exception as e: print(f"startup: {e}")
    finally: db.close()

@app.post("/api/auth/login")
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    from models import User
    user = db.query(User).filter(User.email == body.email, User.isactive == True).first()
    if not user or not verify_password(body.password, user.hashedpw):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(user.id, user.role, user.name)
    return {"access_token": token, "role": user.role, "name": user.name}

@app.get("/api/auth/me")
def me(current=Depends(get_current_user)): return current

@app.post("/api/auth/change-password")
def change_password(body: dict, db: Session = Depends(get_db), current=Depends(get_current_user)):
    from models import User
    old_pw = body.get("old_password", ""); new_pw = body.get("new_password", "")
    if not old_pw or not new_pw: raise HTTPException(400, "Both passwords required")
    if len(new_pw) < 6: raise HTTPException(400, "Password too short")
    uid = current.get("id") if isinstance(current, dict) else None
    if not uid: raise HTTPException(401, "Not authenticated")
    user = db.query(User).filter(User.id == uid).first()
    if not user or not verify_password(old_pw, user.hashedpw):
        raise HTTPException(400, "Current password is incorrect")
    user.hashedpw = hash_password(new_pw)
    db.commit()
    return {"ok": True}

@app.get("/api/users")
def list_users(db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    return db.query(User).all()

@app.post("/api/users")
def create_user(body: dict, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    email = body.get("email", "").strip().lower()
    name  = body.get("name", "").strip()
    pw    = body.get("password", "").strip()
    role  = body.get("role", "cs")
    if not email or not name or not pw: raise HTTPException(400, "Email, name and password required")
    if len(pw) < 6: raise HTTPException(400, "Password must be at least 6 characters")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already in use")
    user = User(email=email, name=name, role=role,
                hashedpw=hash_password(pw), isactive=True)
    db.add(user); db.commit(); db.refresh(user)
    return user

@app.delete("/api/users/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "User not found")
    db.delete(u); db.commit()
    return {"ok": True}

@app.patch("/api/users/{uid}/toggle")
def toggle_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "User not found")
    u.isactive = not u.isactive; db.commit()
    return {"ok": True, "active": u.isactive}

@app.get("/debug")
def debug_page(): return FileResponse("static/debug.html")
