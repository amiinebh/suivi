from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import models, schemas
from database import SessionLocal, engine
import os, json, logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="FreightTrack Pro v36")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
def root():
    return FileResponse("static/index.html")

# ═══════════════════════════════════════════════════════════════════
# QUOTES API
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/quotes")
def get_quotes(status: str = "all", db: Session = Depends(get_db)):
    """Get all quotes, optionally filtered by status"""
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
    """Create new quote and send email"""
    import time
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

    # Send email in background
    bg.add_task(send_quote_email, quote)

    return {"id": str(quote.id), "ref": ref, "status": "sent"}

@app.patch("/api/quotes/{quote_id}")
def update_quote_status(quote_id: int, data: dict, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Update quote status (approve/decline)"""
    quote = db.query(models.Quote).filter(models.Quote.id == quote_id).first()
    if not quote:
        raise HTTPException(404, "Quote not found")

    new_status = data.get("status", "pending")
    quote.status = new_status
    db.commit()

    # Send status update email
    if new_status == "approved":
        bg.add_task(send_quote_approved_email, quote)

    return {"success": True, "status": new_status}

# Email functions
def send_quote_email(quote: models.Quote):
    """Send quote to client via email"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")
        from_email = os.getenv("FROM_EMAIL", smtp_user)

        if not smtp_user:
            print("SMTP not configured, skipping email")
            return

        containers = json.loads(quote.containers) if quote.containers else []
        total = quote.totalTeu * quote.rate

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #218085; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">FreightTrack Pro</h2>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">Your Freight Quote</p>
            </div>
            <div style="padding: 30px; background: #f9f9f9;">
                <h3>Quotation {quote.ref}</h3>
                <p>Dear {quote.client},</p>
                <p>Thank you for your inquiry. Please find your freight quotation below:</p>

                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr style="background: #f0f0f0;">
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Origin (POL)</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{quote.pol}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Destination (POD)</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{quote.pod}</td>
                    </tr>
                    <tr style="background: #f0f0f0;">
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Mode</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{quote.mode}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Total TEU</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{quote.totalTeu}</td>
                    </tr>
                    <tr style="background: #f0f0f0;">
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Rate per TEU</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">€{quote.rate:,.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Amount</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd; font-size: 18px; color: #218085;"><strong>€{total:,.2f}</strong></td>
                    </tr>
                </table>

                {f'<p style="color: #666;"><em>Notes: {quote.notes}</em></p>' if quote.notes else ''}

                <p style="margin-top: 30px;">This quote is valid for 7 days from the issue date.</p>
                <p>If you have any questions, please don't hesitate to contact us.</p>

                <p style="margin-top: 30px;">Best regards,<br><strong>FreightTrack Pro Team</strong></p>
            </div>
            <div style="background: #f0f0f0; padding: 15px; text-align: center; font-size: 12px; color: #666;">
                <p style="margin: 0;">© 2026 FreightTrack Pro. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your Freight Quote {quote.ref}"
        msg["From"] = from_email
        msg["To"] = quote.email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        print(f"Quote email sent to {quote.email}")
    except Exception as e:
        print(f"Email error: {e}")

def send_quote_approved_email(quote: models.Quote):
    """Notify client when quote is approved"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_user = os.getenv("SMTP_USER", "")
        if not smtp_user:
            return

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #22c55e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h2 style="margin: 0;">✓ Quote Approved!</h2>
            </div>
            <div style="padding: 30px; background: #f9f9f9;">
                <p>Dear {quote.client},</p>
                <p>Great news! Your quote <strong>{quote.ref}</strong> has been approved.</p>
                <p>We will now proceed with creating your shipment and will keep you updated on the progress.</p>
                <p style="margin-top: 30px;">Best regards,<br><strong>FreightTrack Pro Team</strong></p>
            </div>
        </body>
        </html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Quote {quote.ref} Approved!"
        msg["From"] = os.getenv("FROM_EMAIL", smtp_user)
        msg["To"] = quote.email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(smtp_user, os.getenv("SMTP_PASS", ""))
            server.send_message(msg)

        print(f"Approval email sent to {quote.email}")
    except Exception as e:
        print(f"Email error: {e}")

# Shipments API (existing endpoints - keep all your current code)
# ... [add your existing shipment endpoints here]
