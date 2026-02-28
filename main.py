from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
import models, schemas, crud, tracker, export
from database import SessionLocal, engine
from typing import Optional
import os, logging

logging.basicConfig(level=logging.INFO)
models.Base.metadata.create_all(bind=engine)

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

# ── Main app ────────────────────────────────────────────────────────────────
@app.get("/")
def root(): return FileResponse("static/index.html")

# ── Client Portal ───────────────────────────────────────────────────────────
@app.get("/track/{ref}")
def client_portal(ref: str):
    return FileResponse("static/portal/index.html")

@app.get("/api/portal/{ref}")
def portal_data(ref: str, db: Session = Depends(get_db)):
    s = crud.get_shipment(db, ref)
    if not s: raise HTTPException(404, "Shipment not found")
    return {
        "ref": s.ref, "ref2": s.ref2, "mode": s.mode,
        "carrier": s.carrier, "vessel": s.vessel,
        "pol": s.pol, "pod": s.pod,
        "etd": s.etd, "eta": s.eta, "status": s.status,
        "client": s.client, "last_tracked": s.last_tracked,
        "events": [{"timestamp":e.timestamp,"location":e.location,
                    "description":e.description,"status":e.status}
                   for e in sorted(s.events, key=lambda x: x.timestamp, reverse=True)]
    }

# ── Shipments CRUD ──────────────────────────────────────────────────────────
@app.get("/api/shipments", response_model=list[schemas.ShipmentOut])
def list_shipments(search:str="", status:str="", mode:str="", db:Session=Depends(get_db)):
    return crud.get_shipments(db, search, status, mode)

@app.post("/api/shipments", response_model=schemas.ShipmentOut)
def create_shipment(s: schemas.ShipmentCreate, db: Session = Depends(get_db)):
    if crud.get_shipment(db, s.ref): raise HTTPException(400,"Reference already exists")
    return crud.create_shipment(db, s)

@app.get("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def get_shipment(sid: int, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404,"Not found")
    return s

@app.patch("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def update_shipment(sid: int, data: schemas.ShipmentUpdate, db: Session = Depends(get_db)):
    s = crud.update_shipment(db, sid, data)
    if not s: raise HTTPException(404,"Not found")
    return s

@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: int, db: Session = Depends(get_db)):
    crud.delete_shipment(db, sid); return {"ok": True}

# ── Tracking ────────────────────────────────────────────────────────────────
@app.post("/api/shipments/{sid}/track")
def track_one(sid: int, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404,"Not found")
    return tracker.track_and_update(db, s)

@app.post("/api/track-all")
def track_all(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(tracker.run_auto_tracking, db)
    return {"message": "Tracking started"}

# ── Comments ────────────────────────────────────────────────────────────────
@app.post("/api/shipments/{sid}/comments", response_model=schemas.CommentOut)
def add_comment(sid: int, data: schemas.CommentCreate, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404,"Not found")
    return crud.add_comment(db, sid, data)

# ── Export ──────────────────────────────────────────────────────────────────
@app.get("/api/export/xlsx")
def export_xlsx(search:str="", status:str="", mode:str="", db:Session=Depends(get_db)):
    ships = crud.get_shipments(db, search, status, mode)
    data  = export.export_shipments_xlsx(ships)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=shipments.xlsx"}
    )

# ── GeoJSON ─────────────────────────────────────────────────────────────────
@app.get("/api/shipments/{sid}/geojson")
def geojson(sid: int, db: Session = Depends(get_db)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404,"Not found")
    gj = tracker.get_geojson(s, db)
    if not gj: raise HTTPException(404,"No map data")
    return gj

# ── Stats ────────────────────────────────────────────────────────────────────
@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    return crud.get_stats(db)

# ── Webhook ──────────────────────────────────────────────────────────────────
@app.post("/api/webhook/shipsgo")
async def webhook(payload: dict, db: Session = Depends(get_db)):
    ref = payload.get("reference") or payload.get("container_number")
    if ref:
        s = crud.get_shipment(db, ref)
        if s: tracker.track_and_update(db, s)
    return {"ok": True}
