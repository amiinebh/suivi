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

from database import run_migrations
run_migrations()

app = FastAPI(title="FreightTrack Pro")
app.mount("/static", StaticFiles(directory="static", html=True), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def start_sched():
    try:
        import scheduler as sched
        sched.start_scheduler()
    except Exception as e:
        print(f"scheduler start error: {e}")

import threading
threading.Thread(target=start_sched, daemon=True).start()

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
            "X-Version": "v36"
        }
    )

@app.get("/track/{ref}")
def client_portal(ref: str):
    return FileResponse("static/portal/index.html")

@app.get("/api/portal/{ref}")
def portal_data(ref: str, db: Session = Depends(get_db)):
    from sqlalchemy import or_
    s = db.query(models.Shipment).filter(
        or_(
            models.Shipment.ref.ilike(ref),
            models.Shipment.booking_no.ilike(ref),
            models.Shipment.ref2.ilike(ref),
            models.Shipment.quotation_number.ilike(ref)
        )
    ).first()
    if not s:
        raise HTTPException(404, "Shipment not found")

    return {
        "ref": s.ref,
        "ref2": s.ref2,
        "mode": s.mode,
        "booking_no": s.booking_no,
        "quotation_number": s.quotation_number,
        "carrier": s.carrier,
        "vessel": s.vessel,
        "pol": s.pol,
        "pod": s.pod,
        "etd": s.etd,
        "eta": s.eta,
        "status": s.status,
        "client": s.client,
        "last_tracked": s.last_tracked,
        "containers": [{"id": c.id, "container_no": c.container_no, "size_type": c.size_type, "seal_no": c.seal_no, "weight": c.weight} for c in s.containers],
        "events": [{"timestamp": e.timestamp, "location": e.location, "description": e.description, "status": e.status} for e in sorted(s.events, key=lambda x: x.timestamp, reverse=True)]
    }

@app.get("/api/shipments", response_model=list[schemas.ShipmentOut])
def list_shipments(q:str="", search:str="", status:str="", mode:str="", db:Session=Depends(get_db), current=Depends(get_current_user)):
    return crud.get_shipments(db, q or search, status, mode)

@app.post("/api/shipments", response_model=schemas.ShipmentOut)
async def create_shipment(request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    try:
        body = await request.json()
    except:
        raise HTTPException(400, "Invalid JSON body")

    ref = body.get("ref", "").strip()
    if not ref: raise HTTPException(400, "Reference is required")
    if crud.get_shipment(db, ref): raise HTTPException(400, "Reference already exists")

    s = schemas.ShipmentCreate(
        ref=ref,
        ref2=body.get("ref2", None),
        booking_no=body.get("booking_no", None),
        mode=body.get("mode", "Ocean"),
        carrier=body.get("carrier", None),
        client=body.get("client", None),
        client_email=body.get("client_email", None),
        note=body.get("note", None),
        pol=body.get("pol", None),
        pod=body.get("pod", None),
        etd=body.get("etd", None),
        eta=body.get("eta", None),
        quotation_number=body.get("quotation_number", None),
        status=body.get("status", "Pending"),
        vessel=body.get("vessel", None),
        direction=body.get("direction", None),
        incoterm=body.get("incoterm", None),
        stuffing_date=body.get("stuffing_date", None),
        agent=body.get("agent", None)
    )
    ship = crud.create_shipment(db, s)

    eq_type = body.get("eq_type", "").strip()
    eq_qty = int(body.get("eq_qty", 0))
    if eq_type and eq_qty > 0:
        for i in range(eq_qty):
            cont = models.Container(shipment_id=ship.id, size_type=eq_type, container_no=f"TBD-{eq_type}-{i+1}")
            db.add(cont)
        try:
            db.commit()
        except:
            db.rollback()
        db.expire(ship)
        db.refresh(ship)

    return ship

@app.get("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
def get_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    s = crud.get_shipment_by_id(db, sid)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.put("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
@app.patch("/api/shipments/{sid}", response_model=schemas.ShipmentOut)
async def update_shipment(sid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    body = await request.json()
    body.pop("eq_type", None)
    body.pop("eq_qty", None)
    data = schemas.ShipmentUpdate(**{k: v for k, v in body.items() if v is not None})

    old_status_val = None
    if "status" in body:
        existing = db.query(models.Shipment).filter(models.Shipment.id == sid).first()
        old_status_val = existing.status if existing else None

    s = crud.update_shipment(db, sid, data)
    if not s: raise HTTPException(404, "Not found")
    db.refresh(s)

    if old_status_val and old_status_val != s.status and s.client_email:
        def notify(ship, olds, news):
            try:
                import email_alerts
                email_alerts.send_status_change_email(ship, olds, news)
            except Exception as ex:
                print(f"email status change email error: {ex}")
        import threading
        threading.Thread(target=notify, args=(s, old_status_val, s.status), daemon=True).start()

    return s

@app.post("/api/shipments/{sid}/send-email")
async def send_client_email(sid: int, request: Request, db: Session = Depends(get_db), current=Depends(get_current_user)):
    body = await request.json()
    subject = body.get("subject", "").strip()
    msg_body = body.get("body", "").strip()
    s = db.query(models.Shipment).filter(models.Shipment.id == sid).first()
    if not s: raise HTTPException(404, "Shipment not found")
    if not s.client_email: raise HTTPException(400, "No client email on this shipment")
    if not subject or not msg_body: raise HTTPException(400, "Subject and body required")
    import email_alerts
    email_alerts.send_custom_client_email(s, subject, msg_body)
    return {"ok": True, "sent_to": s.client_email}

@app.delete("/api/shipments/{sid}")
def delete_shipment(sid: int, db: Session = Depends(get_db), current=Depends(get_current_user)):
    crud.delete_shipment(db, sid)
    return {"ok": True}

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

# ═══════════════════════════════════════════════════════════════════
# QUOTES API
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/quotes")
def get_quotes(status: str = "all", db: Session = Depends(get_db)):
    import json
    query = db.query(models.Quote)
    if status.lower() != "all":
        query = query.filter(models.Quote.status == status.lower())
    quotes = query.order_by(models.Quote.created_at.desc()).all()

    result = []
    for q in quotes:
        containers = json.loads(q.containers) if q.containers else []
        result.append({
            "id": str(q.id),
            "ref": q.ref,
            "client": q.client,
            "email": q.email,
            "pol": q.pol,
            "pod": q.pod,
            "mode": q.mode,
            "rate": q.rate,
            "totalTeu": q.totalTeu,
            "notes": q.notes,
            "status": q.status,
            "containers": containers,
            "created_at": q.created_at
        })
    return result

@app.post("/api/quotes")
def create_quote(data: dict, bg: BackgroundTasks, db: Session = Depends(get_db)):
    import time
    import json
    ref = f"Q{int(time.time())}"

    quote = models.Quote(
        ref=ref,
        client=data.get("client", ""),
        email=data.get("email", ""),
        pol=data.get("pol", ""),
        pod=data.get("pod", ""),
        mode=data.get("mode", "Ocean"),
        rate=float(data.get("rate", 0)),
        totalTeu=float(data.get("totalTeu", 0)),
        notes=data.get("notes", ""),
        status="pending",
        containers=json.dumps(data.get("containers", []))
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)

    bg.add_task(send_quote_email, quote)
    return {"id": str(quote.id), "ref": ref, "status": "sent"}

@app.patch("/api/quotes/{quote_id}")
def update_quote_status(quote_id: int, data: dict, bg: BackgroundTasks, db: Session = Depends(get_db)):
    quote = db.query(models.Quote).filter(models.Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(404, "Quote not found")

    new_status = data.get("status", "pending")
    quote.status = new_status
    db.commit()

    if new_status == "approved":
        bg.add_task(send_quote_approved_email, quote)

    return {"success": True, "status": new_status}

def send_quote_email(quote: models.Quote):
    import os, json, smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("FROM_EMAIL", smtp_user)

    if not smtp_user:
        return

    total = quote.totalTeu * quote.rate
    html = f'''
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #218085; color: white; padding: 20px;">
            <h2 style="margin: 0;">FreightTrack Pro Quote</h2>
        </div>
        <div style="padding: 30px; background: #f9f9f9;">
            <h3>Quotation {quote.ref}</h3>
            <p>Route: {quote.pol} → {quote.pod}</p>
            <p>Mode: {quote.mode} | TEU: {quote.totalTeu}</p>
            <p>Rate: €{quote.rate:,.2f}</p>
            <h2>Total: €{total:,.2f}</h2>
            <p>Notes: {quote.notes}</p>
        </div>
    </body></html>
    '''

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Freight Quote {quote.ref}"
        msg["From"] = from_email
        msg["To"] = quote.email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except Exception as e:
        print(f"Email error: {e}")

def send_quote_approved_email(quote: models.Quote):
    import os, smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_user = os.getenv("SMTP_USER", "")
    if not smtp_user: return

    try:
        html = f"<p>Great news {quote.client}, your quote {quote.ref} is approved!</p>"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Quote {quote.ref} Approved!"
        msg["From"] = os.getenv("FROM_EMAIL", smtp_user)
        msg["To"] = quote.email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(smtp_user, os.getenv("SMTP_PASS", ""))
            server.send_message(msg)
    except Exception as e:
        print(f"Email error: {e}")
