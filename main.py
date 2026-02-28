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
import models, schemas, crud, tracker
from database import SessionLocal, engine
from apscheduler.schedulers.background import BackgroundScheduler
import os

# ── CREATE TABLES ─────────────────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)

# ── AUTO-SEED ADMIN ON FIRST STARTUP ─────────────────────────────────────
def auto_seed():
    db = SessionLocal()
    try:
        if not crud.get_user_by_username(db, "admin"):
            import schemas as s
            user = s.UserCreate(
                username="admin",
                full_name="Administrator",
                email="admin@freighttrack.com",
                password="Admin1234!",
                role="admin"
            )
            hashed = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(user.password)
            crud.create_user(db, user, hashed)
            print("✅ Admin account created automatically: username=admin  password=Admin1234!")
        else:
            print("ℹ️  Admin account already exists.")
    finally:
        db.close()

auto_seed()

app = FastAPI(title="FreightTrack Pro API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

SECRET_KEY = os.getenv("SECRET_KEY", "freighttrack-secret-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def get_password_hash(password): return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username: raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError: raise HTTPException(status_code=401, detail="Invalid token")
    user = crud.get_user_by_username(db, username)
    if not user: raise HTTPException(status_code=401, detail="User not found")
    return user

# ── AUTH ──────────────────────────────────────────────────────────────────
@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token({"sub": user.username}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": token, "token_type": "bearer", "role": user.role, "name": user.full_name}

@app.post("/users/register", response_model=schemas.UserOut)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    if crud.get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Username already exists")
    return crud.create_user(db, user, get_password_hash(user.password))

@app.get("/users/me", response_model=schemas.UserOut)
def me(current_user=Depends(get_current_user)): return current_user

@app.get("/users", response_model=List[schemas.UserOut])
def list_users(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin": raise HTTPException(status_code=403, detail="Admin only")
    return crud.get_all_users(db)

# ── SHIPMENTS ─────────────────────────────────────────────────────────────
@app.get("/shipments", response_model=List[schemas.ShipmentOut])
def get_shipments(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return crud.get_all_shipments(db)

@app.get("/shipments/{shipment_id}", response_model=schemas.ShipmentOut)
def get_shipment(shipment_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = crud.get_shipment(db, shipment_id)
    if not s: raise HTTPException(status_code=404, detail="Not found")
    return s

@app.post("/shipments", response_model=schemas.ShipmentOut)
def create_shipment(shipment: schemas.ShipmentCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if crud.get_shipment_by_ref(db, shipment.ref):
        raise HTTPException(status_code=400, detail="Reference already exists")
    return crud.create_shipment(db, shipment, current_user.id)

@app.put("/shipments/{shipment_id}", response_model=schemas.ShipmentOut)
def update_shipment(shipment_id: int, shipment: schemas.ShipmentCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = crud.update_shipment(db, shipment_id, shipment)
    if not s: raise HTTPException(status_code=404, detail="Not found")
    return s

@app.delete("/shipments/{shipment_id}")
def delete_shipment(shipment_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role != "admin": raise HTTPException(status_code=403, detail="Admin only")
    if not crud.delete_shipment(db, shipment_id): raise HTTPException(status_code=404, detail="Not found")
    return {"message": "Deleted"}

@app.get("/stats")
def get_stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return crud.get_stats(db)

# ── SHIPSGO TRACKING ──────────────────────────────────────────────────────
@app.post("/shipments/{shipment_id}/refresh")
def refresh_single(shipment_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = crud.get_shipment(db, shipment_id)
    if not s: raise HTTPException(status_code=404, detail="Not found")
    if not s.ref2: raise HTTPException(status_code=400, detail="No container number set")
    return tracker.track_and_update(db, s)

@app.post("/tracking/refresh-all")
def refresh_all(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.role not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="Not allowed")
    return {"updated": tracker.run_auto_tracking(db)}

# ── SCHEDULER: auto-refresh every 4 hours ─────────────────────────────────
scheduler = BackgroundScheduler()
def scheduled_tracking():
    db = SessionLocal()
    try: tracker.run_auto_tracking(db)
    finally: db.close()

scheduler.add_job(scheduled_tracking, "interval", hours=4, id="auto_track")
scheduler.start()

# ── FRONTEND ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve(): return FileResponse("static/index.html")
