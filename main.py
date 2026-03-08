from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from auth import get_current_user, require_admin, hash_password, verify_password, create_token
from database import SessionLocal, engine, run_migrations
import models, schemas, crud, export, os, io, logging

logging.basicConfig(level=logging.INFO)
models.Base.metadata.create_all(bind=engine)
try:
    run_migrations()
except Exception as e:
    logging.warning(f"run_migrations failed: {e}")

app = FastAPI(title="FreightTrack Pro")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def root():
    from fastapi.responses import HTMLResponse
    import pathlib
    html_path = pathlib.Path("static/index.html")
    content = html_path.read_text(encoding="utf-8") if html_path.exists() else "<h1>Loading...</h1>"
    return HTMLResponse(content=content)

@app.get("/track/{ref}")
def client_portal(ref: str):
    return FileResponse("static/portal/index.html")

@app.get("/api/portal/{ref}")
def portal_data(ref: str, db: Session = Depends(get_db)):
    s = crud.get_shipment(db, ref)
    if not s:
        raise HTTPException(404, "Shipment not found")
    return {"ref": s.ref, "ref2": s.ref2, "mode": s.mode, "carrier": s.carrier, "vessel": s.vessel, "pol": s.pol, "pod": s.pod, "etd": s.etd, "eta": s.eta, "status": s.status, "client": s.client, "last_tracked": s.last_tracked, "events": [{"timestamp": e.timestamp, "location": e.location, "description": e.description, "status": e.status} for e in sorted(s.events, key=lambda x: x.timestamp, reverse=True)]}

@app.get("/api/shipments", response_model=list[schemas.ShipmentOut])
def list_shipments(q:str="", search:str="", status:str="", mode:str="", db:Session=Depends(get_db), current=Depends(get_current_user)):
    return crud.get_shipments(db, q or search, status, mode)

@app.post("/api/shipments", response_model=schemas.ShipmentOut)
async def create_shipment(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    body = await request.json()
    ref = (body.get("ref") or "").strip()
    if not ref:
        raise HTTPException(400, "Reference is required")
    if crud.get_shipment(db, ref):
        raise HTTPException(400, "Reference already exists")
    allowed = set(schemas.ShipmentCreate.model_fields.keys())
    data = {k:(v if v != "" else None) for k,v in body.items() if k in allowed}
    data["ref"] = ref
    data.setdefault("mode", "Ocean")
    data.setdefault("status", "Pending")
    return crud.create_shipment(db, schemas.ShipmentCreate(**data))

@app.get("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def get_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s:
        raise HTTPException(404, "Not found")
    return s

@app.put("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
async def update_shipment(sid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    body = await request.json()
    allowed = set(schemas.ShipmentUpdate.model_fields.keys())
    data = schemas.ShipmentUpdate(**{k:(v if v != "" else None) for k,v in body.items() if k in allowed})
    s = crud.update_shipment(db, sid, data)
    if not s:
        raise HTTPException(404, "Not found")
    return s

@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    crud.delete_shipment(db, sid)
    return {"ok": True}

@app.post("/api/shipments/{sid}/comments", response_model=schemas.CommentOut)
def add_comment(sid: int, data: schemas.CommentCreate, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s:
        raise HTTPException(404, "Not found")
    return crud.add_comment(db, sid, data)

@app.get("/api/export/xlsx")
def export_xlsx(search:str="", status:str="", mode:str="", db:Session=Depends(get_db)):
    ships = crud.get_shipments(db, search, status, mode)
    data = export.export_shipments_xlsx(ships)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=shipments.xlsx"})

@app.get("/api/kpis")
def get_kpis(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_kpis(db)

@app.get("/api/stats")
def stats(db: Session = Depends(get_db), current=Depends(get_current_user)):
    return crud.get_stats(db)

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

@app.post("/api/auth/login")
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    from models import User
    user = db.query(User).filter(User.email==body.email, User.is_active==True).first()
    if not user or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    token = create_token(user.id, user.role, user.name)
    return {"access_token": token, "role": user.role, "name": user.name}

@app.get("/api/auth/me")
def me(current=Depends(get_current_user)):
    return current

@app.post("/api/shipments/bulk-import")
async def bulk_import(file: UploadFile = File(...), db: Session = Depends(get_db), current=Depends(get_current_user)):
    import openpyxl
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    created, skipped, errors = [], [], []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_data = {headers[i]:(str(v).strip() if v is not None else "") for i,v in enumerate(row) if i < len(headers)}
        ref = row_data.get("ref", "").strip()
        if not ref:
            continue
        if db.query(models.Shipment).filter(models.Shipment.ref == ref).first():
            skipped.append(ref)
            continue
        try:
            from datetime import datetime
            s = models.Shipment(
                ref=ref,
                ref2=row_data.get("container/awb", "") or row_data.get("ref2", ""),
                booking_no=row_data.get("booking no", "") or row_data.get("booking_no", ""),
                mode=row_data.get("mode", "Ocean"),
                direction=row_data.get("direction", ""),
                carrier=row_data.get("carrier", ""),
                vessel=row_data.get("vessel", ""),
                client=row_data.get("client", ""),
                client_email=row_data.get("client email", "") or row_data.get("client_email", ""),
                shipper=row_data.get("shipper", ""),
                consignee=row_data.get("consignee", ""),
                incoterm=row_data.get("incoterm", ""),
                agent=row_data.get("agent", ""),
                pol=row_data.get("pol", ""),
                pod=row_data.get("pod", ""),
                etd=row_data.get("etd", ""),
                eta=row_data.get("eta", ""),
                status=row_data.get("status", "") or "Pending",
                stuffing_date=row_data.get("stuffing date", "") or row_data.get("stuffing_date", ""),
                notes=row_data.get("notes", "") or row_data.get("note", ""),
                created_at=datetime.utcnow().isoformat(),
            )
            db.add(s)
            db.commit()
            created.append(ref)
        except Exception as e:
            db.rollback()
            errors.append({"ref": ref, "error": str(e)})
    return {"created": len(created), "skipped": len(skipped), "errors": errors, "refs_created": created}

@app.get("/api/kpi-report")
def kpi_report(db: Session = Depends(get_db)):
    k = crud.get_kpis(db)
    total = k.get("total", 0)
    insights = [f"Network volume stands at {total} shipments."] if total else []
    return {"kpis": k, "insights": insights}

@app.on_event("startup")
def on_startup():
    try:
        run_migrations()
    except Exception as e:
        logging.warning(f"startup migrations failed: {e}")
    db = SessionLocal()
    try:
        from models import User
        if not db.query(User).filter(User.role == "admin").first():
            admin = User(email=os.getenv("ADMIN_EMAIL", "admin@freighttrack.com"), name="Admin", role="admin", hashed_pw=hash_password(os.getenv("ADMIN_PASSWORD", "Admin1234!")), is_active=True)
            db.add(admin)
            db.commit()
    except Exception as e:
        logging.warning(f"startup admin failed: {e}")
    finally:
        db.close()
