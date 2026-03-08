from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from auth import get_current_user, hash_password, verify_password, create_token
from database import SessionLocal, engine, run_migrations
import models, schemas, crud, export, os, io

models.Base.metadata.create_all(bind=engine)
try:
    run_migrations()
except Exception:
    pass

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
    import pathlib
    p = pathlib.Path("static/index.html")
    return HTMLResponse(p.read_text(encoding="utf-8") if p.exists() else "<h1>Loading...</h1>")

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status":"ok"}

@app.post("/api/auth/login")
def login(body: schemas.LoginRequest, db: Session = Depends(get_db)):
    from models import User
    user = db.query(User).filter(User.email == body.email, User.is_active == True).first()
    if not user or not verify_password(body.password, user.hashed_pw):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": create_token(user.id, user.role, user.name), "role": user.role, "name": user.name}

@app.get("/api/auth/me")
def me(current=Depends(get_current_user)):
    return current

@app.get("/api/shipments", response_model=list[schemas.ShipmentOut])
def list_shipments(q:str="", search:str="", status:str="", mode:str="", db:Session=Depends(get_db), current=Depends(get_current_user)):
    return crud.get_shipments(db, q or search, status, mode)

@app.post("/api/shipments/bulk-import")
async def bulk_import(file: UploadFile = File(...), db: Session = Depends(get_db), current=Depends(get_current_user)):
    import openpyxl
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    created = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_data = {headers[i]:(str(v).strip() if v is not None else "") for i,v in enumerate(row) if i < len(headers)}
        ref = row_data.get("ref", "").strip()
        if not ref:
            continue
        if db.query(models.Shipment).filter(models.Shipment.ref == ref).first():
            continue
        s = models.Shipment(ref=ref, ref2=row_data.get("container/awb", ""), booking_no=row_data.get("booking no", ""), mode=row_data.get("mode", "Ocean"), carrier=row_data.get("carrier", ""), client=row_data.get("client", ""), pol=row_data.get("pol", ""), pod=row_data.get("pod", ""), etd=row_data.get("etd", ""), eta=row_data.get("eta", ""), status=row_data.get("status", "") or "Pending")
        db.add(s)
        db.commit()
        created.append(ref)
    return {"created": len(created), "refs_created": created}

@app.get("/api/export/xlsx")
def export_xlsx(search:str="", status:str="", mode:str="", db:Session=Depends(get_db)):
    ships = crud.get_shipments(db, search, status, mode)
    data = export.export_shipments_xlsx(ships)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=shipments.xlsx"})

@app.get("/api/kpi-report")
def kpi_report(db: Session = Depends(get_db)):
    return {"kpis": crud.get_kpis(db), "insights": []}
