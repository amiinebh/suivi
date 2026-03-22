from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Response, Request
from auth import get_current_user, require_admin, hash_password, verify_password, create_token
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
import models, schemas, crud, export
from database import SessionLocal, engine
import os, logging

logging.basicConfig(level=logging.INFO)
models.Base.metadata.create_all(bind=engine)
# Run safe column migrations for existing PostgreSQL tables
from database import run_migrations
run_migrations()

app = FastAPI(title="FreightTrack Pro")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()


# ── Pages ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    from fastapi.responses import HTMLResponse
    import os, pathlib
    html_path = pathlib.Path("static/index.html")
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
    else:
        content = "<h1>Loading...</h1>"
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Version": "v25"
        }
    )

@app.get("/track/{ref}")
def client_portal(ref: str): return FileResponse("static/portal/index.html")

# ── Portal API ───────────────────────────────────────────────────────────────
@app.get("/api/portal/{ref}")
def portal_data(ref: str, db: Session = Depends(get_db)):
    s = crud.get_shipment(db, ref)
    if not s: raise HTTPException(404, "Shipment not found")
    return {
        "ref": s.ref, "ref2": s.ref2, "mode": s.mode,
        "carrier": s.carrier, "vessel": s.vessel,
        "pol": s.pol, "pod": s.pod, "etd": s.etd,
        "eta": s.eta, "status": s.status,
        "client": s.client, "last_tracked": s.last_tracked,
        "events": [{"timestamp": e.timestamp, "location": e.location,
                    "description": e.description, "status": e.status}
                   for e in sorted(s.events, key=lambda x: x.timestamp, reverse=True)]
    }

# ── Shipments ────────────────────────────────────────────────────────────────
@app.get("/api/shipments", response_model=list[schemas.ShipmentOut])
def list_shipments(q:str="", search:str="", status:str="", mode:str="", db:Session=Depends(get_db), current=Depends(get_current_user)):
    return crud.get_shipments(db, q or search, status, mode)

@app.post("/api/shipments", response_model=schemas.ShipmentOut)
async def create_shipment(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    """Accept both JSON body and handle all optional fields gracefully."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    ref = (body.get("ref") or "").strip()
    if not ref:
        raise HTTPException(400, "Reference is required")
    if crud.get_shipment(db, ref):
        raise HTTPException(400, "Reference already exists")
    allowed_c = set(schemas.ShipmentCreate.model_fields.keys())
    s_data = {k: (v if v != "" else None) for k, v in body.items() if k in allowed_c}
    s_data["ref"] = ref
    s_data.setdefault("mode", "Ocean")
    s_data.setdefault("status", "Pending")
    s = schemas.ShipmentCreate(**s_data)
    ship = crud.create_shipment(db, s)
    return ship

@app.get("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def get_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.put("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
async def update_shipment(sid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    body = await request.json()
    allowed = set(schemas.ShipmentUpdate.model_fields.keys())
    filtered = {k: (v if v != "" else None) for k, v in body.items() if k in allowed}
    data = schemas.ShipmentUpdate(**filtered)
    s = crud.update_shipment(db, sid, data)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    crud.delete_shipment(db, sid); return {"ok": True}

# ── Tracking ─────────────────────────────────────────────────────────────────
@app.post("/api/shipments/{sid}/track")
def track_one(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return tracker.track_and_update(db, s)

@app.post("/api/track-all")
# ── Comments ──────────────────────────────────────────────────────────────────
@app.post("/api/shipments/{sid}/comments", response_model=schemas.CommentOut)
def add_comment(sid: int, data: schemas.CommentCreate, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return crud.add_comment(db, sid, data)

# ── Export ────────────────────────────────────────────────────────────────────
@app.get("/api/export/xlsx")
def export_xlsx(search:str="", status:str="", mode:str="", db:Session=Depends(get_db), current=Depends(get_current_user)):
    ships = crud.get_shipments(db, search, status, mode)
    data  = export.export_shipments_xlsx(ships)
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=shipments.xlsx"})

# ── GeoJSON ───────────────────────────────────────────────────────────────────
@app.get("/api/shipments/{sid}/geojson")
def geojson(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    gj = tracker.get_geojson(s, db)
    if not gj: raise HTTPException(404, "No map data")
    return gj


@app.get("/api/kpis")
def get_kpis(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_kpis(db)

# ── Stats ─────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
def stats(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_stats(db)

# ── Webhook ───────────────────────────────────────────────────────────────────
@app.post("/api/webhook/shipsgo")
async def webhook(payload: dict, db: Session = Depends(get_db)):
    ref = payload.get("reference") or payload.get("container_number")
    if ref:
        s = crud.get_shipment(db, ref)
        if s: tracker.track_and_update(db, s)
    return {"ok": True}

# ── Health check ──────────────────────────────────────────────────────────────

# ══ PDF EXPORTS ════════════════════════════════════════════════════════════
@app.get("/api/shipments/{sid}/pdf")
def shipment_pdf(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    """Generate PDF report for a single shipment."""
    import pdf_export
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Shipment not found")
    pdf_bytes = pdf_export.generate_shipment_pdf(s)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="shipment_{s.ref}.pdf"'}
    )

@app.get("/api/dashboard/pdf")
def dashboard_pdf(db: Session = Depends(get_db), current=Depends(get_current_user)):
    """Generate dashboard summary PDF."""
    import pdf_export
    stats = crud.get_stats(db)
    ships = crud.get_shipments(db, "", "", "")
    pdf_bytes = pdf_export.generate_dashboard_pdf(stats, ships)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="dashboard_{datetime.now().strftime("%Y%m%d")}.pdf"'}
    )

# ══ CONTAINERS (Multi-container per shipment) ═════════════════════════════
@app.get("/api/shipments/{sid}/containers")
def get_containers(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    """Get all containers for a shipment."""
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Shipment not found")
    return s.containers

@app.post("/api/shipments/{sid}/containers")
def add_container(sid: int, data: dict, db: Session = Depends(get_db), current=Depends(get_current_user)):
    """Add a container to a shipment."""
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Shipment not found")
    from models import Container
    cont = Container(
        shipment_id=sid,
        container_no=data.get("container_no"),
        seal_no=data.get("seal_no"),
        size_type=data.get("size_type"),
        weight=data.get("weight")
    )
    db.add(cont)
    db.commit()
    db.refresh(cont)
    return cont

@app.delete("/api/containers/{cid}")
def delete_container(cid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    """Delete a container."""
    from models import Container
    cont = db.query(Container).filter(Container.id == cid).first()
    if not cont: raise HTTPException(404, "Container not found")
    db.delete(cont)
    db.commit()
    return {"ok": True}


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

# ══ Shipsgo Proxy ══════════════════════════════════════════════════════
import httpx
SHIPSGO_BASE = "https://api.shipsgo.com/v2"

@app.api_route("/proxy/shipsgo/{path:path}", methods=["GET","POST","PATCH","DELETE"])
async def shipsgo_proxy(path: str, request: Request):
    api_key = request.headers.get("X-Shipsgo-User-Token","")
    body = await request.body()
    params = dict(request.query_params)
    hdrs = {"X-Shipsgo-User-Token":api_key,"Accept":"application/json","Content-Type":"application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(request.method, f"{SHIPSGO_BASE}/{path}", headers=hdrs, params=params, content=body)
    try: data = resp.json()
    except: data = {"raw": resp.text}
    return JSONResponse(content=data, status_code=resp.status_code)

@app.get("/debug")
def debug_page(): return FileResponse("static/debug.html")

# ══ Auth ═══════════════════════════════════════════════════════════════
def ensure_admin(db):
    from models import User
    if not db.query(User).filter(User.role=="admin").first():
        admin = User(email=os.getenv("ADMIN_EMAIL","admin@freighttrack.com"),
            name="Admin", role="admin",
            hashed_pw=hash_password(os.getenv("ADMIN_PASSWORD","Admin1234!")),
            is_active=True)
        db.add(admin); db.commit()
        print("✅ Default admin created")

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
    user = db.query(User).filter(User.email==body.email, User.is_active==True).first()
    if not user or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(user.id, user.role, user.name)
    return {"access_token": token, "role": user.role, "name": user.name}

@app.get("/api/auth/me")
def me(current=Depends(get_current_user)): return current

@app.post("/api/auth/change-password")
def change_password(body: dict, db: Session = Depends(get_db), current=Depends(get_current_user)):
    from models import User
    old_pw = body.get("old_password",""); new_pw = body.get("new_password","")
    if not old_pw or not new_pw: raise HTTPException(400,"Both passwords required")
    if len(new_pw)<6: raise HTTPException(400,"New password must be at least 6 characters")
    user = db.query(User).filter(User.id==int(current["sub"])).first()
    if not user or not verify_password(old_pw, user.hashed_pw):
        raise HTTPException(401,"Current password is incorrect")
    user.hashed_pw = hash_password(new_pw); db.commit()
    return {"message":"Password changed successfully"}

# ══ User Management ════════════════════════════════════════════════════
@app.get("/api/users")
def list_users(db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    users = db.query(User).order_by(User.id).all()
    return [{"id":u.id,"email":u.email,"name":u.name,"role":u.role,
             "is_active":u.is_active,"created_at":str(u.created_at)} for u in users]

@app.post("/api/users")
def create_user(body: schemas.UserCreate, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    if db.query(User).filter(User.email==body.email).first():
        raise HTTPException(409,"Email already exists")
    u = User(email=body.email, name=body.name, role=body.role,
             hashed_pw=hash_password(body.password), is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return {"id":u.id,"email":u.email,"name":u.name,"role":u.role}

@app.patch("/api/users/{uid}/toggle")
def toggle_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(404,"User not found")
    if u.role=="admin": raise HTTPException(400,"Cannot deactivate admin")
    u.is_active = not u.is_active; db.commit()
    return {"id":u.id,"is_active":u.is_active}

@app.delete("/api/users/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(404,"User not found")
    if u.role=="admin": raise HTTPException(400,"Cannot delete admin")
    db.delete(u); db.commit()
    return {"deleted": uid}

# ══ Bulk Import ════════════════════════════════════════════════════════
from fastapi import UploadFile, File
import io

@app.post("/api/shipments/bulk-import")
async def bulk_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                      current=Depends(get_current_user)):
    import openpyxl
    from datetime import datetime
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    headers = [str(c.value).strip().lower().replace(" ","_") if c.value else "" for c in next(ws.iter_rows(min_row=1,max_row=1))]
    created, skipped, errors = [], [], []

    VALID_STATUSES = ["Confirmed","Booked","Stuffed","Sailing","Arrived","Closed","Canceled"]

    def parse_date(val):
        if not val: return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
            try: return datetime.strptime(str(val).strip(), fmt).strftime("%Y-%m-%d")
            except: pass
        return None

    for row in ws.iter_rows(min_row=2, values_only=True):
        row_data = {headers[i]:(str(v).strip() if v is not None else "") for i,v in enumerate(row) if i<len(headers)}
        ref = row_data.get("ref","").strip()
        if not ref: continue
        if db.query(models.Shipment).filter(models.Shipment.ref==ref).first():
            skipped.append(ref); continue
        try:
            raw_status = row_data.get("status","").strip()
            status = raw_status if raw_status in VALID_STATUSES else "Confirmed"
            etd = parse_date(row_data.get("etd",""))
            eta = parse_date(row_data.get("eta",""))
            teu_raw = row_data.get("teu","")
            try: teu = int(float(teu_raw)) if teu_raw else None
            except: teu = None
            s = models.Shipment(
                ref=ref,
                ref2=row_data.get("ref2",""),
                booking_no=row_data.get("booking_no",""),
                mode=row_data.get("mode","Ocean"),
                carrier=row_data.get("carrier",""),
                shipper=row_data.get("shipper",""),
                consignee=row_data.get("consignee",""),
                client=row_data.get("client",""),
                client_email=row_data.get("client_email",""),
                pol=row_data.get("pol",""),
                pod=row_data.get("pod",""),
                etd=etd,
                eta=eta,
                status=status,
                incoterm=row_data.get("incoterm",""),
                vessel=row_data.get("vessel",""),
                voyage=row_data.get("voyage",""),
                teu=teu,
                note=row_data.get("note",""),
                created_at=datetime.utcnow().isoformat()
            )
            db.add(s); db.commit(); created.append(ref)
        except Exception as e: errors.append({"ref":ref,"error":str(e)})
    return {"created":len(created),"skipped":len(skipped),"errors":errors,"refs_created":created}


@app.post("/api/shipments/{sid}/track-debug")
def track_debug(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    import requests as req_lib
    s = db.query(models.Shipment).filter(models.Shipment.id==sid).first()
    if not s: return {"error":"Not found"}
    token = os.getenv("SHIPSGO_TOKEN") or os.getenv("SHIPSGO_API_KEY","")
    hdrs = {"X-Shipsgo-User-Token":token,"Accept":"application/json","Content-Type":"application/json"}
    result = {"token_set":bool(token),"ref":s.ref,"container":s.ref2,"shipsgo_id":s.shipsgo_id}
    if s.shipsgo_id:
        r = req_lib.get(f"https://api.shipsgo.com/v2/ocean/shipments/{s.shipsgo_id}",headers=hdrs,timeout=20)
        result["get"] = {"status":r.status_code,"body":r.json() if r.content else {}}
    return result

# ══ Shipsgo Deep Debug ════════════════════════════════════════════════
@app.get("/api/debug/shipsgo")
def shipsgo_debug(db: Session = Depends(get_db)):
    """Full Shipsgo connectivity + POST test — returns raw API responses."""
    import requests as req_lib
    token = os.getenv("SHIPSGO_TOKEN") or os.getenv("SHIPSGO_API_KEY","")
    result = {"token_set": bool(token), "token_preview": token[:6]+"…" if token else ""}

    hdrs = {"X-Shipsgo-User-Token": token, "Accept": "application/json",
            "Content-Type": "application/json"}

    # 1. List existing ocean shipments (verifies token works)
    try:
        r = req_lib.get("https://api.shipsgo.com/v2/ocean/shipments?take=3",
                        headers=hdrs, timeout=15)
        result["list_status"] = r.status_code
        result["list_body"] = r.json() if r.content else {}
    except Exception as e:
        result["list_error"] = str(e)

    # 2. Try a test POST with a known valid CMA CGM container prefix
    test_body = {"container_number": "CMAU0000001", "carrier": "CMDU",
                 "reference": "DEBUG-TEST-001"}
    try:
        r2 = req_lib.post("https://api.shipsgo.com/v2/ocean/shipments",
                          headers=hdrs, json=test_body, timeout=15)
        result["test_post_status"] = r2.status_code
        result["test_post_body"] = r2.json() if r2.content else {}
        # If 409, grab the existing id
        if r2.status_code == 409:
            result["test_post_note"] = "409 = already exists (token works!)"
    except Exception as e:
        result["test_post_error"] = str(e)

    # 3. Check all shipments in DB that have no shipsgo_id
    unregistered = db.query(models.Shipment).filter(
        models.Shipment.shipsgo_id == None,
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    result["unregistered_shipments"] = [
        {"id": s.id, "ref": s.ref, "container": s.ref2, "carrier": s.carrier}
        for s in unregistered
    ]

    return result

@app.post("/api/shipments/{sid}/force-register")
def force_register(sid: int, db: Session = Depends(get_db)):
    """Force re-register a specific shipment with Shipsgo and return full raw response."""
    import requests as req_lib
    s = db.query(models.Shipment).filter(models.Shipment.id == sid).first()
    if not s: raise HTTPException(404, "Shipment not found")
    token = os.getenv("SHIPSGO_TOKEN") or os.getenv("SHIPSGO_API_KEY","")
    hdrs = {"X-Shipsgo-User-Token": token, "Accept": "application/json",
            "Content-Type": "application/json"}
    ref = (s.ref or "").strip()
    if len(ref) < 5: ref = ref + "-FTP"
    scac = _t.resolve_scac(s.ref2 or "", s.carrier or "")
    body = {"container_number": s.ref2, "reference": ref[:128]}
    if scac: body["carrier"] = scac
    if s.booking_no: body["booking_number"] = s.booking_no
    if s.client_email: body["followers"] = [s.client_email]

    try:
        r = req_lib.post("https://api.shipsgo.com/v2/ocean/shipments",
                         headers=hdrs, json=body, timeout=20)
        d = {}
        try: d = r.json()
        except: d = {"raw": r.text}
        # Save shipsgo_id if we got one
        sid_val = (d.get("shipment") or {}).get("id")
        if sid_val and not s.shipsgo_id:
            s.shipsgo_id = sid_val; db.commit()
        return {"status": r.status_code, "body": d, "body_sent": body,
                "scac_resolved": scac, "shipsgo_id_saved": sid_val}
    except Exception as e:
        return {"error": str(e), "body_sent": body}

# ══ Terminal49 Debug (no auth — public) ═══════════════════════════════
@app.get("/api/debug/t49")
def t49_debug(db: Session = Depends(get_db)):
    """Test Terminal49 API connectivity + register container SEKU6272191."""
    import requests as req_lib
    key = os.getenv("TERMINAL49_API_KEY", "")
    result = {"key_set": bool(key), "key_preview": key[:6]+"…" if key else "NOT SET"}

    hdrs = {
        "Authorization": f"Token {key}",
        "Content-Type": "application/vnd.api+json",
        "Accept": "application/json"
    }

    # 1. List existing tracking requests
    try:
        r = req_lib.get("https://api.terminal49.com/v2/tracking_requests?page[size]=3",
                        headers=hdrs, timeout=15)
        result["list_status"] = r.status_code
        try: result["list_body"] = r.json()
        except: result["list_body"] = r.text[:300]
    except Exception as e:
        result["list_error"] = str(e)

    # 2. Test POST with real container
    body = {"data": {"type": "tracking_request", "attributes": {
        "request_type": "container",
        "request_number": "SEKU6272191",
        "scac": "CMDU"
    }}}
    try:
        r2 = req_lib.post("https://api.terminal49.com/v2/tracking_requests",
                          headers=hdrs, json=body, timeout=15)
        result["test_post_status"] = r2.status_code
        try: result["test_post_body"] = r2.json()
        except: result["test_post_body"] = r2.text[:300]
    except Exception as e:
        result["test_post_error"] = str(e)

    # 3. Show unregistered shipments in DB
    unregistered = db.query(models.Shipment).filter(
        models.Shipment.ref2 != None,
        models.Shipment.ref2 != ""
    ).all()
    result["shipments_in_db"] = [
        {"id": s.id, "ref": s.ref, "container": s.ref2,
         "carrier": s.carrier, "t49_note": s.note}
        for s in unregistered
    ]
    return result

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT","8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)


@app.post("/api/seed-samples")
def seed_samples(db: Session = Depends(get_db)):
    """Seed 15 realistic sample shipments for testing."""
    samples=[
        {"ref":"FT-2026-001","mode":"Ocean","carrier":"MSC","client":"Maroc Textiles","shipper":"Guangzhou Mills","consignee":"Maroc Textiles SARL","pol":"Shanghai","pod":"Casablanca","etd":"2026-01-05","eta":"2026-02-10","status":"Delivered","direction":"Import","incoterm":"FOB","booking_no":"MSC1234567","vessel":"MSC DIANA"},
        {"ref":"FT-2026-002","mode":"Ocean","carrier":"CMA CGM","client":"Atlas Pharma","shipper":"Atlas Pharma","consignee":"Lyon Distrib","pol":"Casablanca","pod":"Marseille","etd":"2026-01-12","eta":"2026-01-18","status":"Delivered","direction":"Export","incoterm":"CIF","vessel":"CMA CGM BELEM"},
        {"ref":"FT-2026-003","mode":"Air","carrier":"Royal Air Maroc","client":"TechImport MA","shipper":"Shenzhen Electronics","consignee":"TechImport MA","pol":"Hong Kong","pod":"Casablanca","etd":"2026-01-20","eta":"2026-01-21","status":"Delivered","direction":"Import","incoterm":"EXW"},
        {"ref":"FT-2026-004","mode":"Ocean","carrier":"Maersk","client":"Maroc Textiles","shipper":"Maroc Textiles","consignee":"Hamburg Buyer GmbH","pol":"Casablanca","pod":"Hamburg","etd":"2026-01-25","eta":"2026-02-15","status":"Delivered","direction":"Export","incoterm":"FOB","vessel":"MAERSK ELBA"},
        {"ref":"FT-2026-005","mode":"Ocean","carrier":"MSC","client":"Casa Ceramics","shipper":"Valencia Ceramics","consignee":"Casa Ceramics","pol":"Valencia","pod":"Casablanca","etd":"2026-02-01","eta":"2026-02-08","status":"Delivered","direction":"Import","incoterm":"CFR","vessel":"MSC ANNA"},
        {"ref":"FT-2026-006","mode":"Ocean","carrier":"COSCO","client":"Atlas Pharma","shipper":"Tianjin Chem","consignee":"Atlas Pharma","pol":"Tianjin","pod":"Casablanca","etd":"2026-02-05","eta":"2026-03-18","status":"Delayed","direction":"Import","incoterm":"CIF","vessel":"COSCO ARIES"},
        {"ref":"FT-2026-007","mode":"Ocean","carrier":"CMA CGM","client":"Sahara Foods","shipper":"Sahara Foods SA","consignee":"Rotterdam Buyer","pol":"Agadir","pod":"Rotterdam","etd":"2026-02-10","eta":"2026-02-20","status":"Delivered","direction":"Export","incoterm":"FOB","vessel":"CMA CGM TAGE"},
        {"ref":"FT-2026-008","mode":"Air","carrier":"Air France Cargo","client":"TechImport MA","shipper":"Paris Supplier","consignee":"TechImport MA","pol":"Paris CDG","pod":"Casablanca","etd":"2026-02-14","eta":"2026-02-14","status":"Delivered","direction":"Import","incoterm":"DAP"},
        {"ref":"FT-2026-009","mode":"Ocean","carrier":"Maersk","client":"Casa Ceramics","shipper":"Casa Ceramics","consignee":"Antwerp Buyer","pol":"Casablanca","pod":"Antwerp","etd":"2026-02-18","eta":"2026-03-01","status":"Sailing","direction":"Export","incoterm":"CIF","vessel":"MAERSK COPENHAGEN"},
        {"ref":"FT-2026-010","mode":"Ocean","carrier":"MSC","client":"Maroc Textiles","shipper":"Chennai Mills","consignee":"Maroc Textiles","pol":"Chennai","pod":"Casablanca","etd":"2026-02-20","eta":"2026-03-25","status":"In Transit","direction":"Import","incoterm":"FOB","vessel":"MSC ROMA"},
        {"ref":"FT-2026-011","mode":"Ocean","carrier":"Hapag-Lloyd","client":"Sahara Foods","shipper":"Sahara Foods","consignee":"Barcelona Buyer","pol":"Casablanca","pod":"Barcelona","etd":"2026-02-25","eta":"2026-03-05","status":"Arrived","direction":"Export","incoterm":"EXW","vessel":"ALGECIRAS EXPRESS"},
        {"ref":"FT-2026-012","mode":"Air","carrier":"Lufthansa Cargo","client":"Atlas Pharma","shipper":"Frankfurt Pharma","consignee":"Atlas Pharma","pol":"Frankfurt","pod":"Casablanca","etd":"2026-03-01","eta":"2026-03-02","status":"Delivered","direction":"Import","incoterm":"DDP"},
        {"ref":"FT-2026-013","mode":"Ocean","carrier":"CMA CGM","client":"Maroc Textiles","shipper":"Istanbul Fabric","consignee":"Maroc Textiles","pol":"Istanbul","pod":"Casablanca","etd":"2026-03-03","eta":"2026-03-10","status":"Pending","direction":"Import","incoterm":"CFR","vessel":"CMA CGM TAGE"},
        {"ref":"FT-2026-014","mode":"Ocean","carrier":"COSCO","client":"Casa Ceramics","shipper":"Casa Ceramics","consignee":"Shanghai Buyer","pol":"Casablanca","pod":"Shanghai","etd":"2026-03-05","eta":"2026-04-10","status":"Booked","direction":"Export","incoterm":"FOB"},
        {"ref":"FT-2026-015","mode":"Ocean","carrier":"MSC","client":"TechImport MA","shipper":"Ningbo Tech","consignee":"TechImport MA","pol":"Ningbo","pod":"Casablanca","etd":"2026-03-06","eta":"2026-04-15","status":"Confirmed","direction":"Import","incoterm":"EXW","vessel":"MSC FIAMMETTA"},
    ]
    allowed={c.name for c in models.Shipment.__table__.columns}
    added=0
    for s in samples:
        if not db.query(models.Shipment).filter(models.Shipment.ref==s["ref"]).first():
            db.add(models.Shipment(**{k:v for k,v in s.items() if k in allowed})); added+=1
    db.commit()
    return {"added":added,"message":f"Seeded {added} sample shipments"}



@app.get("/api/kpi-report")
def kpi_report(db: Session = Depends(get_db)):
    k = crud.get_kpis(db)
    total = k.get("total",0)
    delayed = k.get("delayed",0)
    delivered = k.get("delivered",0)
    active = k.get("active",0)
    pending = k.get("pending",0)
    insights = []
    if total:
        insights.append(f"Network volume stands at {total} shipments.")
        insights.append(f"Delivered/arrived shipments represent {delivered} records, while delayed shipments are {delayed}.")
        insights.append(f"Active in-transit operations total {active}, with {pending} still pending or booked.")
    if k.get("avg_transit") and k.get("avg_transit") != "N/A":
        insights.append(f"Average transit time is {k['avg_transit']}.")
    if k.get("delay_rate"):
        insights.append(f"Delay rate is {k['delay_rate']} and on-time completion rate is {k.get('on_time_rate','0%')}.")
    if k.get("by_carrier"):
        top = k['by_carrier'][0]
        insights.append(f"Top carrier by volume is {top['name']} with {top['count']} shipments.")
    if k.get("by_client"):
        topc = k['by_client'][0]
        insights.append(f"Largest client by shipment count is {topc['name']} with {topc['count']} shipments.")
    if k.get("top_pods"):
        tp = k['top_pods'][0]
        insights.append(f"Top destination port is {tp['name']} with {tp['count']} shipments.")
    return {"kpis": k, "insights": insights}
