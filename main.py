from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File
from auth import get_current_user, require_admin, hash_password, verify_password, create_token
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
import models, schemas, crud, export
from database import SessionLocal, engine
import os, logging, io
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

@app.get("/")
def root():
    from fastapi.responses import HTMLResponse
    import pathlib
    html_path = pathlib.Path("static/index.html")
    content = html_path.read_text(encoding="utf-8") if html_path.exists() else "<h1>Loading...</h1>"
    return HTMLResponse(content=content, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache", "Expires": "0", "X-Version": "v26"
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

# Shipments
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
    ref = (body.get("ref") or "").strip()
    if not ref: raise HTTPException(400, "Reference is required")
    if crud.get_shipment(db, ref): raise HTTPException(400, "Reference already exists")
    allowed = set(schemas.ShipmentCreate.model_fields.keys())
    sdata = {}
    for k, v in body.items():
        if k not in allowed: continue
        sdata[k] = v.strip() if isinstance(v, str) and v.strip() != "" else (None if isinstance(v, str) else v)
    sdata["ref"] = ref
    sdata.setdefault("mode", "Ocean")
    sdata.setdefault("status", "Confirmed")
    try:
        s = schemas.ShipmentCreate(**sdata)
        return crud.create_shipment(db, s)
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, f"Failed to create shipment: {str(e)}")

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

# Tracking
@app.post("/api/shipments/{sid}/track")
def track_one(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    import tracker
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return tracker.track_and_update(db, s)

@app.post("/api/track-all")
def track_all(db: Session = Depends(get_db), current=Depends(get_current_user)):
    import tracker
    for s in crud.get_shipments(db, "", "", ""):
        try: tracker.track_and_update(db, s)
        except: pass
    return {"ok": True}

# Comments
@app.post("/api/shipments/{sid}/comments", response_model=schemas.CommentOut)
def add_comment(sid: int, data: schemas.CommentCreate, db: Session = Depends(get_db),
                current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return crud.add_comment(db, sid, data)

# Export
@app.get("/api/export/xlsx")
def export_xlsx(search: str = "", status: str = "", mode: str = "",
                db: Session = Depends(get_db), current=Depends(get_current_user)):
    ships = crud.get_shipments(db, search, status, mode)
    data = export.export_shipments_xlsx(ships)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=shipments.xlsx"})

# KPIs & Stats
@app.get("/api/kpis")
def get_kpis(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_kpis(db)

@app.get("/api/stats")
def stats(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_stats(db)

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        from sqlalchemy import text; db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

# Containers
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
    cont = Container(shipment_id=sid, containerno=data.get("containerno"),
                     sealno=data.get("sealno"), sizetype=data.get("sizetype"),
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

# Email
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

# Webhook
@app.post("/api/webhook/shipsgo")
async def webhook(payload: dict, db: Session = Depends(get_db)):
    ref = payload.get("reference") or payload.get("container_number")
    if ref:
        s = crud.get_shipment(db, ref)
        if s:
            import tracker; tracker.track_and_update(db, s)
    return {"ok": True}

# Shipsgo Proxy
import httpx
SHIPSGO_BASE = "https://api.shipsgo.com/v2"

@app.api_route("/proxy/shipsgo/{path:path}", methods=["GET","POST","PATCH","DELETE"])
async def shipsgo_proxy(path: str, request: Request):
    api_key = request.headers.get("X-Shipsgo-User-Token", "")
    body = await request.body()
    params = dict(request.query_params)
    hdrs = {"X-Shipsgo-User-Token": api_key, "Accept": "application/json",
            "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(request.method, f"{SHIPSGO_BASE}/{path}",
                                    headers=hdrs, params=params, content=body)
    try: data = resp.json()
    except: data = resp.text
    return JSONResponse(content=data, status_code=resp.status_code)

@app.get("/debug")
def debug_page(): return FileResponse("static/debug.html")

# Bulk Import
@app.post("/api/shipments/bulk-import")
async def bulk_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                      current=Depends(get_current_user)):
    import openpyxl
    from datetime import datetime
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    headers = [str(c.value).strip().lower().replace(" ", "_") if c.value else ""
               for c in next(ws.iter_rows(min_row=1, max_row=1))]
    created, skipped, errors = [], [], []
    VALID = ["Confirmed","Booked","Stuffed","Sailing","Arrived","Closed","Canceled"]
    def parse_date(val):
        if not val: return None
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"]:
            try: return datetime.strptime(str(val).strip(), fmt).strftime("%Y-%m-%d")
            except: pass
        return None
    for row in ws.iter_rows(min_row=2, values_only=True):
        rd = {headers[i]: (str(v).strip() if v is not None else "")
              for i, v in enumerate(row) if i < len(headers)}
        ref = rd.get("ref", "").strip()
        if not ref: continue
        if db.query(models.Shipment).filter(models.Shipment.ref == ref).first():
            skipped.append(ref); continue
        try:
            raw_status = rd.get("status", "").strip()
            teu_raw = rd.get("teu")
            try: teu = int(float(teu_raw)) if teu_raw else None
            except: teu = None
            s = models.Shipment(
                ref=ref, ref2=rd.get("ref2",""), bookingno=rd.get("bookingno",""),
                mode=rd.get("mode","Ocean"), carrier=rd.get("carrier",""),
                shipper=rd.get("shipper",""), consignee=rd.get("consignee",""),
                client=rd.get("client",""), clientemail=rd.get("clientemail",""),
                pol=rd.get("pol",""), pod=rd.get("pod",""),
                etd=parse_date(rd.get("etd")), eta=parse_date(rd.get("eta")),
                status=raw_status if raw_status in VALID else "Confirmed",
                incoterm=rd.get("incoterm",""), vessel=rd.get("vessel",""),
                voyage=rd.get("voyage",""), teu=teu, note=rd.get("note",""),
                createdat=datetime.utcnow().isoformat()
            )
            db.add(s); db.commit(); created.append(ref)
        except Exception as e:
            errors.append({"ref": ref, "error": str(e)})
    return {"created": len(created), "skipped": len(skipped), "errors": errors, "refs": created}

# Seed Samples
@app.post("/api/seed-samples")
def seed_samples(db: Session = Depends(get_db)):
    allowed = {c.name for c in models.Shipment.__table__.columns}
    samples = [
        {"ref":"FT-2026-001","mode":"Ocean","carrier":"MSC","client":"Maroc Textiles","pol":"Shanghai","pod":"Casablanca","etd":"2026-01-05","eta":"2026-02-10","status":"Closed","incoterm":"FOB","vessel":"MSC DIANA"},
        {"ref":"FT-2026-002","mode":"Ocean","carrier":"CMA CGM","client":"Atlas Pharma","pol":"Casablanca","pod":"Marseille","etd":"2026-01-12","eta":"2026-01-18","status":"Closed","incoterm":"CIF"},
        {"ref":"FT-2026-003","mode":"Air","carrier":"Royal Air Maroc","client":"TechImport MA","pol":"Hong Kong","pod":"Casablanca","etd":"2026-01-20","eta":"2026-01-21","status":"Closed","incoterm":"EXW"},
        {"ref":"FT-2026-004","mode":"Ocean","carrier":"Maersk","client":"Maroc Textiles","pol":"Casablanca","pod":"Hamburg","etd":"2026-01-25","eta":"2026-02-15","status":"Closed","incoterm":"FOB","vessel":"MAERSK ELBA"},
        {"ref":"FT-2026-005","mode":"Ocean","carrier":"MSC","client":"Casa Ceramics","pol":"Valencia","pod":"Casablanca","etd":"2026-02-01","eta":"2026-02-08","status":"Closed","incoterm":"CFR","vessel":"MSC ANNA"},
        {"ref":"FT-2026-009","mode":"Ocean","carrier":"Maersk","client":"Casa Ceramics","pol":"Casablanca","pod":"Antwerp","etd":"2026-02-18","eta":"2026-03-01","status":"Sailing","incoterm":"CIF","vessel":"MAERSK COPENHAGEN"},
        {"ref":"FT-2026-010","mode":"Ocean","carrier":"MSC","client":"Maroc Textiles","pol":"Chennai","pod":"Casablanca","etd":"2026-02-20","eta":"2026-03-25","status":"Sailing","incoterm":"FOB","vessel":"MSC ROMA"},
        {"ref":"FT-2026-013","mode":"Ocean","carrier":"CMA CGM","client":"Maroc Textiles","pol":"Istanbul","pod":"Casablanca","etd":"2026-03-03","eta":"2026-03-10","status":"Confirmed","incoterm":"CFR"},
        {"ref":"FT-2026-015","mode":"Ocean","carrier":"MSC","client":"TechImport MA","pol":"Ningbo","pod":"Casablanca","etd":"2026-03-06","eta":"2026-04-15","status":"Confirmed","incoterm":"EXW","vessel":"MSC FIAMMETTA"},
    ]
    added = 0
    for s in samples:
        if not db.query(models.Shipment).filter(models.Shipment.ref == s["ref"]).first():
            db.add(models.Shipment(**{k: v for k, v in s.items() if k in allowed}))
            added += 1
    db.commit()
    return {"added": added, "message": f"Seeded {added} sample shipments"}

@app.get("/api/kpi-report")
def kpi_report(db: Session = Depends(get_db)):
    k = crud.get_kpis(db)
    insights = []
    total = k.get("total", 0)
    if total:
        insights.append(f"Network volume stands at {total} shipments.")
        insights.append(f"Delivered: {k.get('delivered',0)}, delayed: {k.get('delayed',0)}.")
    if k.get("bycarrier"):
        top = k["bycarrier"][0]
        insights.append(f"Top carrier: {top['name']} with {top['count']} shipments.")
    return {"kpis": k, "insights": insights}

# PDF
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
    from datetime import datetime
    pdf_bytes = pdfexport.generate_dashboard_pdf(crud.get_stats(db), crud.get_shipments(db,"","",""))
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=dashboard_{datetime.now().strftime('%Y%m%d')}.pdf"})

# Auth & Users
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
    if len(new_pw) < 6: raise HTTPException(400, "New password must be at least 6 characters")
    user = db.query(User).filter(User.id == int(current["sub"])).first()
    if not user or not verify_password(old_pw, user.hashedpw):
        raise HTTPException(401, "Current password is incorrect")
    user.hashedpw = hash_password(new_pw); db.commit()
    return {"message": "Password changed successfully"}

@app.get("/api/users")
def list_users(db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    return [{"id": u.id, "email": u.email, "name": u.name, "role": u.role,
             "isactive": u.isactive, "createdat": str(u.createdat)}
            for u in db.query(User).order_by(User.id).all()]

@app.post("/api/users")
def create_user(body: schemas.UserCreate, db: Session = Depends(get_db),
                current=Depends(require_admin)):
    from models import User
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "Email already exists")
    u = User(email=body.email, name=body.name, role=body.role,
             hashedpw=hash_password(body.password), isactive=True)
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}

@app.patch("/api/users/{uid}/toggle")
def toggle_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "User not found")
    if u.role == "admin": raise HTTPException(400, "Cannot deactivate admin")
    u.isactive = not u.isactive; db.commit()
    return {"id": u.id, "isactive": u.isactive}

@app.delete("/api/users/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db), current=Depends(require_admin)):
    from models import User
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "User not found")
    if u.role == "admin": raise HTTPException(400, "Cannot delete admin")
    db.delete(u); db.commit()
    return {"deleted": uid}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

@app.get("/debug-user-fields")
def debug_user_fields():
    from models import User
    return {"columns": [c.key for c in User.__table__.columns]}
