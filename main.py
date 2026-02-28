from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
import models, schemas, crud, tracker, export
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

# ── Auto-scheduler ──────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()
def scheduled_track():
    db = SessionLocal()
    try: tracker.run_auto_tracking(db)
    finally: db.close()
scheduler.add_job(scheduled_track, "interval", hours=6)
scheduler.start()

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
def list_shipments(search:str="", status:str="", mode:str="", db:Session=Depends(get_db)):
    return crud.get_shipments(db, search, status, mode)

@app.post("/api/shipments", response_model=schemas.ShipmentOut)
async def create_shipment(request: Request, db: Session = Depends(get_db)):
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
        note=body.get("note") or None,
        pol=body.get("pol") or None,
        pod=body.get("pod") or None,
        etd=body.get("etd") or None,
        eta=body.get("eta") or None,
        status=body.get("status") or "Pending",
    )
    return crud.create_shipment(db, s)

@app.get("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def get_shipment(sid: int, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.patch("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
async def update_shipment(sid: int, request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    data = schemas.ShipmentUpdate(**{k: v or None for k, v in body.items() if v is not None})
    s = crud.update_shipment(db, sid, data)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: int, db: Session = Depends(get_db)):
    crud.delete_shipment(db, sid); return {"ok": True}

# ── Tracking ─────────────────────────────────────────────────────────────────
@app.post("/api/shipments/{sid}/track")
def track_one(sid: int, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return tracker.track_and_update(db, s)

@app.post("/api/track-all")
def track_all(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(tracker.run_auto_tracking, db)
    return {"message": "Tracking started"}

# ── Comments ──────────────────────────────────────────────────────────────────
@app.post("/api/shipments/{sid}/comments", response_model=schemas.CommentOut)
def add_comment(sid: int, data: schemas.CommentCreate, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return crud.add_comment(db, sid, data)

# ── Export ────────────────────────────────────────────────────────────────────
@app.get("/api/export/xlsx")
def export_xlsx(search:str="", status:str="", mode:str="", db:Session=Depends(get_db)):
    ships = crud.get_shipments(db, search, status, mode)
    data  = export.export_shipments_xlsx(ships)
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=shipments.xlsx"})

# ── GeoJSON ───────────────────────────────────────────────────────────────────
@app.get("/api/shipments/{sid}/geojson")
def geojson(sid: int, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    gj = tracker.get_geojson(s, db)
    if not gj: raise HTTPException(404, "No map data")
    return gj


@app.get("/api/kpis")
def get_kpis(db: Session = Depends(get_db)):
    return crud.get_kpis(db)

# ── Stats ─────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
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
@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}


# ── Shipsgo Proxy (avoids CORS from browser) ────────────────────────────────
import httpx
from fastapi import Request as ProxyRequest

SHIPSGO_BASE = "https://api.shipsgo.com/v2"

@app.api_route("/proxy/shipsgo/{path:path}", methods=["GET","POST","PATCH","DELETE"])
async def shipsgo_proxy(path: str, request: ProxyRequest):
    api_key = request.headers.get("X-Shipsgo-User-Token","")
    body    = await request.body()
    params  = dict(request.query_params)
    hdrs = {
        "X-Shipsgo-User-Token": api_key,
        "Accept":               "application/json",
        "Content-Type":         "application/json",
    }
    url = f"{SHIPSGO_BASE}/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(
            method=request.method, url=url,
            headers=hdrs, params=params, content=body,
        )
    try:    data = resp.json()
    except: data = {"raw": resp.text}
    return JSONResponse(
        content=data, status_code=resp.status_code,
        headers={
            "X-Shipsgo-Credits-Remaining": resp.headers.get("X-Shipsgo-Credits-Remaining",""),
            "X-Shipsgo-Credits-Cost":      resp.headers.get("X-Shipsgo-Credits-Cost",""),
        }
    )

# ── Debug page ───────────────────────────────────────────────────────────────
@app.get("/debug")
def debug_page():
    from fastapi.responses import FileResponse
    return FileResponse("static/debug.html")

# ── Track debug endpoint ─────────────────────────────────────────────────────
@app.post("/api/shipments/{sid}/track-debug")
def track_debug(sid: int, db: Session = Depends(get_db)):
    import requests as req_lib
    s = db.query(models.Shipment).filter(models.Shipment.id == sid).first()
    if not s: return {"error": "Shipment not found"}
    token = os.getenv("SHIPSGO_TOKEN") or os.getenv("SHIPSGO_API_KEY","")
    hdrs  = {"X-Shipsgo-User-Token": token, "Accept": "application/json",
             "Content-Type": "application/json"}
    result = {"token_set": bool(token), "ref": s.ref,
              "container": s.ref2, "shipsgo_id": s.shipsgo_id}
    if s.shipsgo_id:
        r = req_lib.get(f"https://api.shipsgo.com/v2/ocean/shipments/{s.shipsgo_id}",
                        headers=hdrs, timeout=20)
        result["get"] = {"status": r.status_code, "body": r.json() if r.content else {}}
    else:
        r = req_lib.post("https://api.shipsgo.com/v2/ocean/shipments",
                         headers=hdrs, json={"container_number": s.ref2 or ""}, timeout=20)
        result["post"] = {"status": r.status_code, "body": r.json() if r.content else {}}
    return result


# ══════════════════════════════════════════════════════════════════════════════
# AUTH & USER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════
import auth as auth_module
from auth import get_current_user, require_admin, hash_password, verify_password, create_token

# ── Auto-create admin on first run ───────────────────────────────────────────
def ensure_admin(db):
    from models import User
    if not db.query(User).filter(User.role=="admin").first():
        admin = User(
            email     = os.getenv("ADMIN_EMAIL","admin@freighttrack.com"),
            name      = "Admin",
            role      = "admin",
            hashed_pw = hash_password(os.getenv("ADMIN_PASSWORD","Admin1234!")),
            is_active = True,
        )
        db.add(admin); db.commit()
        print("✅ Default admin created:", admin.email)

@app.on_event("startup")
def on_startup():
    # Import ALL models so create_all knows about every table including users
    import models as _models
    from database import Base, engine, SessionLocal, run_migrations
    Base.metadata.create_all(bind=engine)   # creates users table if missing
    run_migrations()                         # adds any missing columns
    db = SessionLocal()
    try: ensure_admin(db)
    except Exception as e:
        print(f"⚠️ ensure_admin error: {e}")
    finally: db.close()

# ── Login ─────────────────────────────────────────────────────────────────────
@app.post("/api/auth/login")
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    from models import User
    user = db.query(User).filter(User.email == body.email, User.is_active == True).first()
    if not user or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(user.id, user.role, user.name)
    return {"access_token": token, "role": user.role, "name": user.name}

# ── List users (admin only) ───────────────────────────────────────────────────
@app.get("/api/users")
def list_users(db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    users = db.query(User).order_by(User.id).all()
    return [{"id":u.id,"email":u.email,"name":u.name,"role":u.role,
             "is_active":u.is_active,"created_at":u.created_at} for u in users]

# ── Create user (admin only) ──────────────────────────────────────────────────
@app.post("/api/users")
def create_user(body: schemas.UserCreate, db: Session = Depends(get_db),
                current=Depends(require_admin)):
    from models import User
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "Email already exists")
    u = User(email=body.email, name=body.name, role=body.role,
             hashed_pw=hash_password(body.password), is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    return {"id":u.id,"email":u.email,"name":u.name,"role":u.role}

# ── Toggle user active (admin only) ──────────────────────────────────────────
@app.patch("/api/users/{uid}/toggle")
def toggle_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(404,"User not found")
    if u.role == "admin": raise HTTPException(400,"Cannot deactivate admin")
    u.is_active = not u.is_active; db.commit()
    return {"id":u.id,"is_active":u.is_active}

# ── Delete user (admin only) ──────────────────────────────────────────────────
@app.delete("/api/users/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id==uid).first()
    if not u: raise HTTPException(404,"User not found")
    if u.role == "admin": raise HTTPException(400,"Cannot delete admin")
    db.delete(u); db.commit()
    return {"deleted": uid}

# ── Me endpoint ───────────────────────────────────────────────────────────────
@app.get("/api/auth/me")
def me(current=Depends(get_current_user)):
    return current
