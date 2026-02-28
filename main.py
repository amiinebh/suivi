from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from typing import Optional, List
import os

import models, schemas, tracker
from database import SessionLocal, engine
from apscheduler.schedulers.background import BackgroundScheduler

models.Base.metadata.create_all(bind=engine)

_pwd           = CryptContext(schemes=["bcrypt"], deprecated="auto")
ADMIN_USER     = "admin"
ADMIN_PASS     = "Admin1234!"
SECRET_KEY     = os.getenv("SECRET_KEY", "freighttrack-secret-2026")
ALGORITHM      = "HS256"
TOKEN_MINUTES  = 480
oauth2_scheme  = OAuth2PasswordBearer(tokenUrl="token")

# â”€â”€ SEED â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def seed():
    db = SessionLocal()
    try:
        u = db.query(models.User).filter(models.User.username == ADMIN_USER).first()
        if u:
            u.hashed_password = _pwd.hash(ADMIN_PASS)
            u.role = "admin"
            db.commit()
            print(f"âœ… Admin password RESET â†’ {ADMIN_USER} / {ADMIN_PASS}")
        else:
            db.add(models.User(
                username=ADMIN_USER, full_name="Administrator",
                email="admin@freighttrack.com",
                hashed_password=_pwd.hash(ADMIN_PASS), role="admin"
            ))
            db.commit()
            print(f"âœ… Admin CREATED â†’ {ADMIN_USER} / {ADMIN_PASS}")
    except Exception as e:
        db.rollback()
        print(f"âš ï¸ Seed error: {e}")
    finally:
        db.close()

seed()

# â”€â”€ APP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app = FastAPI(title="FreightTrack Pro")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try:    yield db
    finally: db.close()

def create_access_token(data, expires_delta=None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username: raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user: raise HTTPException(status_code=401, detail="User not found")
    return user

# â”€â”€ EMERGENCY RESET ENDPOINT (no auth needed) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/reset-admin")
def reset_admin():
    """Emergency: resets admin password to Admin1234! â€” remove after first login."""
    db = SessionLocal()
    try:
        u = db.query(models.User).filter(models.User.username == ADMIN_USER).first()
        if u:
            u.hashed_password = _pwd.hash(ADMIN_PASS)
            u.role = "admin"
            db.commit()
            return {"message": f"âœ… Admin password reset to: {ADMIN_PASS}", "username": ADMIN_USER}
        else:
            db.add(models.User(
                username=ADMIN_USER, full_name="Administrator",
                email="admin@freighttrack.com",
                hashed_password=_pwd.hash(ADMIN_PASS), role="admin"
            ))
            db.commit()
            return {"message": f"âœ… Admin created. Username: {ADMIN_USER}  Password: {ADMIN_PASS}"}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()

# â”€â”€ AUTH â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not _pwd.verify(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token({"sub": user.username}, timedelta(minutes=TOKEN_MINUTES))
    return {"access_token": token, "token_type": "bearer", "role": user.role, "name": user.full_name}

@app.get("/users/me", response_model=schemas.UserOut)
def me(current_user=Depends(get_current_user)): return current_user

@app.get("/users", response_model=List[schemas.UserOut])
def list_users(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin": raise HTTPException(403, "Admin only")
    return db.query(models.User).all()

@app.post("/users/register", response_model=schemas.UserOut)
def register(user: schemas.UserCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role != "admin": raise HTTPException(403, "Admin only")
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(400, "Username exists")
    u = models.User(username=user.username, full_name=user.full_name,
                    email=user.email, hashed_password=_pwd.hash(user.password), role=user.role)
    db.add(u); db.commit(); db.refresh(u); return u

# â”€â”€ SHIPMENTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.get("/shipments", response_model=List[schemas.ShipmentOut])
def get_shipments(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(models.Shipment).order_by(models.Shipment.id.desc()).all()

@app.get("/shipments/{shipment_id}", response_model=schemas.ShipmentOut)
def get_shipment(shipment_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(models.Shipment).filter(models.Shipment.id == shipment_id).first()
    if not s: raise HTTPException(404, "Not found")
    return s

@app.post("/shipments", response_model=schemas.ShipmentOut)
def create_shipment(shipment: schemas.ShipmentCreate, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    if db.query(models.Shipment).filter(models.Shipment.ref == shipment.ref).first():
        raise HTTPException(400, "Reference exists")
    obj = models.Shipment(**shipment.model_dump(), created_by=current_user.id)
    db.add(obj); db.commit(); db.refresh(obj); return obj

@app.put("/shipments/{shipment_id}", response_model=schemas.ShipmentOut)
def update_shipment(shipment_id: int, shipment: schemas.ShipmentCreate,
                    db: Session = Depends(get_db), _=Depends(get_current_user)):
    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment_id).first()
    if not obj: raise HTTPException(404, "Not found")
    for k, v in shipment.model_dump().items(): setattr(obj, k, v)
    db.commit(); db.refresh(obj); return obj

@app.delete("/shipments/{shipment_id}")
def delete_shipment(shipment_id: int, db: Session = Depends(get_db),
                    current_user=Depends(get_current_user)):
    if current_user.role != "admin": raise HTTPException(403, "Admin only")
    obj = db.query(models.Shipment).filter(models.Shipment.id == shipment_id).first()
    if not obj: raise HTTPException(404, "Not found")
    db.delete(obj); db.commit(); return {"message": "Deleted"}

@app.get("/stats")
def get_stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    all_s = db.query(models.Shipment).all()
    return {"total": len(all_s),
            "in_transit": sum(1 for s in all_s if s.status == "In Transit"),
            "delivered":  sum(1 for s in all_s if s.status == "Delivered"),
            "issues":     sum(1 for s in all_s if s.status in ("Delayed","Customs")),
            "ocean":      sum(1 for s in all_s if s.mode == "Ocean"),
            "road":       sum(1 for s in all_s if s.mode == "Road"),
            "air":        sum(1 for s in all_s if s.mode == "Air")}

# â”€â”€ SHIPSGO â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.post("/shipments/{shipment_id}/refresh")
def refresh_single(shipment_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.query(models.Shipment).filter(models.Shipment.id == shipment_id).first()
    if not s: raise HTTPException(404, "Not found")
    if not s.ref2: raise HTTPException(400, "No container number")
    return tracker.track_and_update(db, s)

@app.post("/tracking/refresh-all")
def refresh_all(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role not in ("admin","operator"): raise HTTPException(403, "Not allowed")
    return {"updated": tracker.run_auto_tracking(db)}

# â”€â”€ SCHEDULER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
scheduler = BackgroundScheduler()
def scheduled_tracking():
    db = SessionLocal()
    try:    tracker.run_auto_tracking(db)
    finally: db.close()

scheduler.add_job(scheduled_tracking, "interval", hours=4, id="auto_track")
scheduler.start()

# â”€â”€ STATIC â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve(): return FileResponse("static/index.html")
