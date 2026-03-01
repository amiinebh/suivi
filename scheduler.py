"""
Daily alert scheduler — runs at 08:00 Morocco time (UTC+1 = 07:00 UTC).
Checks all active shipments and sends emails via Resend.
Uses a sent-log in DB to avoid sending duplicate emails per day.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, date
from sqlalchemy.orm import Session
import models, email_alerts
from database import SessionLocal
import logging

log = logging.getLogger(__name__)

ACTIVE_STATUSES = {"pending", "booked", "sailing", "transit", "in transit"}

def _today() -> date:
    return datetime.utcnow().date()

def _days_until(date_str: str) -> int:
    try:
        return (datetime.strptime(date_str[:10], "%Y-%m-%d").date() - _today()).days
    except:
        return 999

def _days_since(date_str: str) -> int:
    return -_days_until(date_str)

def run_daily_alerts():
    log.info("[scheduler] Running daily alert check…")
    db: Session = SessionLocal()
    today_str = _today().isoformat()
    try:
        shipments = db.query(models.Shipment).all()
        sent = 0
        for s in shipments:
            status = (s.status or "").lower()
            if status not in ACTIVE_STATUSES:
                continue

            # ── ETD passed (Pending/Booked only) ──
            if s.etd and status in {"pending", "booked"}:
                if _days_since(s.etd) >= 0:
                    key = f"etd_passed:{s.id}:{s.etd[:10]}"
                    if not _already_sent(db, key, today_str):
                        email_alerts.send_etd_passed(s)
                        _mark_sent(db, key, today_str)
                        sent += 1

            # ── ETA reached ──
            if s.eta and _days_since(s.eta) >= 0:
                key_team = f"eta_reached_team:{s.id}:{s.eta[:10]}"
                if not _already_sent(db, key_team, today_str):
                    email_alerts.send_eta_reached_team(s)
                    _mark_sent(db, key_team, today_str)
                    sent += 1
                key_client = f"eta_reached_client:{s.id}:{s.eta[:10]}"
                if s.client_email and not _already_sent(db, key_client, today_str):
                    email_alerts.send_eta_reached_client(s)
                    _mark_sent(db, key_client, today_str)
                    sent += 1

            # ── Arriving in 3 days ──
            if s.eta and _days_until(s.eta) == 3:
                key_team = f"arriving_soon_team:{s.id}:{s.eta[:10]}"
                if not _already_sent(db, key_team, today_str):
                    email_alerts.send_arriving_soon_team(s, 3)
                    _mark_sent(db, key_team, today_str)
                    sent += 1
                key_client = f"arriving_soon_client:{s.id}:{s.eta[:10]}"
                if s.client_email and not _already_sent(db, key_client, today_str):
                    email_alerts.send_arriving_soon_client(s, 3)
                    _mark_sent(db, key_client, today_str)
                    sent += 1

            # ── Stuffing date reached (EXW) ──
            if s.stuffing_date and (s.incoterm or "").upper() == "EXW":
                if status in {"pending", "booked"} and _days_since(s.stuffing_date) >= 0:
                    key = f"stuffing:{s.id}:{s.stuffing_date[:10]}"
                    if not _already_sent(db, key, today_str):
                        email_alerts.send_stuffing_date_reached(s)
                        _mark_sent(db, key, today_str)
                        sent += 1

        log.info(f"[scheduler] Done — {sent} email(s) sent.")
    except Exception as e:
        log.error(f"[scheduler] Error: {e}")
    finally:
        db.close()

# ── Simple sent-log using ShipmentEvent table as a log store ──────────────
def _already_sent(db: Session, key: str, today: str) -> bool:
    return db.query(models.AlertLog).filter(
        models.AlertLog.key == key,
        models.AlertLog.sent_date == today
    ).first() is not None

def _mark_sent(db: Session, key: str, today: str):
    log_entry = models.AlertLog(key=key, sent_date=today)
    db.add(log_entry)
    db.commit()

# ── Start scheduler ───────────────────────────────────────────────────────
_scheduler = None

def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    # 07:00 UTC = 08:00 Morocco (UTC+1)
    _scheduler.add_job(run_daily_alerts, CronTrigger(hour=7, minute=0))
    _scheduler.start()
    log.info("[scheduler] Started — daily alerts at 07:00 UTC (08:00 Morocco)")

def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
