from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Response, Request
from auth import get_current_user, require_admin, hash_password, verify_password, create_token, decode_token
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
    s = schemas.ShipmentCreate(
        ref=ref,
        ref2=body.get("ref2") or None,
        booking_no=body.get("booking_no") or None,
        mode=body.get("mode") or "Ocean",
        carrier=body.get("carrier") or None,
        client=body.get("client") or None,
        client_email=body.get("client_email") or None,
        shipper=body.get("shipper") or None,
        consignee=body.get("consignee") or None,
        incoterm=body.get("incoterm") or None,
        note=body.get("note") or None,
        pol=body.get("pol") or None,
        pod=body.get("pod") or None,
        etd=body.get("etd") or None,
        eta=body.get("eta") or None,
        quotation_number=body.get("quotation_number") or None,
        status=body.get("status") or "Pending",
        vessel=body.get("vessel") or None,
        teu=int(body["teu"]) if body.get("teu") else None,
    )
    try:
        ship = crud.create_shipment(db, s)
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"DB Create Error: {str(e)}")
    return ship

@app.get("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def get_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.put("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
async def update_shipment(sid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    body = await request.json()
    # Build update dict — handle teu (int) and other nullable fields carefully
    update_dict = {}
    for k, v in body.items():
        if k == "teu":
            update_dict[k] = int(v) if v else None
        elif v is not None:
            update_dict[k] = v or None
    data = schemas.ShipmentUpdate(**update_dict)
    try:
        s = crud.update_shipment(db, sid, data)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"DB Update Error: {str(e)}")
    if not s: raise HTTPException(404, "Not found")
    return s


@app.patch("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
async def patch_shipment(sid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    """PATCH alias for update — used by frontend."""
    body = await request.json()
    update_dict2 = {}
    for k, v in body.items():
        if k == "teu": update_dict2[k] = int(v) if v else None
        elif v is not None: update_dict2[k] = v or None
    data = schemas.ShipmentUpdate(**update_dict2)
    try:
        s = crud.update_shipment(db, sid, data)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"DB Patch Error: {str(e)}")
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
def export_xlsx(search:str="", status:str="", mode:str="", token:str="", db:Session=Depends(get_db)):
    if not token:
        raise HTTPException(401, "Not authenticated")
    decode_token(token)  # raises 401 if invalid
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
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1,max_row=1))]
    created, skipped, errors = [], [], []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_data = {headers[i]:(str(v).strip() if v is not None else "") for i,v in enumerate(row) if i<len(headers)}
        ref = row_data.get("ref","").strip()
        if not ref: continue
        if db.query(models.Shipment).filter(models.Shipment.ref==ref).first():
            skipped.append(ref); continue
        try:
            from datetime import datetime
            s = models.Shipment(ref=ref, ref2=row_data.get("ref2",""),
                booking_no=row_data.get("booking_no",""), mode=row_data.get("mode","Ocean"),
                carrier=row_data.get("carrier",""), client=row_data.get("client",""),
                client_email=row_data.get("client_email",""), pol=row_data.get("pol",""),
                pod=row_data.get("pod",""), status="Pending",
                created_at=datetime.utcnow().isoformat())
            db.add(s); db.commit(); created.append(ref)
        except Exception as e: errors.append({"ref":ref,"error":str(e)})
    return {"created":len(created),"skipped":len(skipped),"errors":errors,"refs_created":created}

# ══ Debug track ════════════════════════════════════════════════════════
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

