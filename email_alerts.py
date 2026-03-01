import os, resend
from datetime import datetime

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("ALERT_FROM_EMAIL", "onboarding@resend.dev")
TO_EMAILS_RAW  = os.getenv("ALERT_TO_EMAILS", "")
TEAM_EMAILS    = [e.strip() for e in TO_EMAILS_RAW.split(",") if e.strip()]
APP_URL        = os.getenv("APP_URL", "https://suivi-production-18db.up.railway.app")

COLORS = {
    "danger":  "#ef4444",
    "warning": "#f59e0b",
    "info":    "#4f8ef7",
    "success": "#22c55e",
}

def _badge(status):
    c = {"Pending":"#64748b","Sailing":"#4f8ef7","Transit":"#4f8ef7",
         "Arrived":"#06b6d4","Delivered":"#22c55e","Delayed":"#ef4444"}.get(status,"#64748b")
    return f'<span style="background:{c}22;color:{c};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700">{status}</span>'

def _html_wrapper(title: str, color: str, icon: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f0f4ff;font-family:'Inter',Arial,sans-serif">
<div style="max-width:600px;margin:32px auto;background:#fff;border-radius:16px;
  box-shadow:0 4px 32px rgba(79,142,247,.12);overflow:hidden">
  <!-- Header -->
  <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:28px 32px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <div style="width:40px;height:40px;background:linear-gradient(135deg,#4f8ef7,#6c63ff);
        border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px">🚢</div>
      <div>
        <div style="color:#fff;font-size:16px;font-weight:800">FreightTrack Pro</div>
        <div style="color:rgba(255,255,255,.5);font-size:11px">Shipment Alert</div>
      </div>
    </div>
    <div style="background:{color}22;border:1px solid {color}44;border-left:4px solid {color};
      border-radius:10px;padding:14px 16px;color:#fff">
      <div style="font-size:22px;margin-bottom:6px">{icon}</div>
      <div style="font-size:17px;font-weight:700">{title}</div>
    </div>
  </div>
  <!-- Body -->
  <div style="padding:28px 32px">
    {body}
  </div>
  <!-- Footer -->
  <div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 32px;
    text-align:center;font-size:11px;color:#94a3b8">
    FreightTrack Pro · Automated alert · {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
  </div>
</div>
</body></html>"""

def _shipment_body(s, extra_rows="") -> str:
    track_url = f"{APP_URL}/track/{s.ref}"
    rows = [
        ("Reference",  f"<strong>{s.ref}</strong>"),
        ("Status",     _badge(s.status or "Pending")),
        ("Route",      f"{s.pol or '—'} → {s.pod or '—'}"),
        ("Carrier",    s.carrier or "—"),
        ("ETD",        (s.etd or "—")[:10]),
        ("ETA",        (s.eta or "—")[:10]),
        ("Client",     s.client or "—"),
    ]
    if s.booking_no: rows.append(("Booking #", s.booking_no))
    if s.incoterm:   rows.append(("Incoterm",  s.incoterm))
    if s.direction:  rows.append(("Direction", s.direction))
    table = "".join(
        f'''<tr>
          <td style="padding:8px 0;font-size:12px;color:#64748b;font-weight:600;
            width:130px;vertical-align:top">{label}</td>
          <td style="padding:8px 0;font-size:13px;color:#0f172a;font-weight:500">{val}</td>
        </tr>'''
        for label, val in rows
    )
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px">{table}{extra_rows}</table>
    <a href="{track_url}" style="display:inline-block;background:linear-gradient(135deg,#4f8ef7,#6c63ff);
      color:#fff;padding:12px 24px;border-radius:10px;text-decoration:none;font-size:13px;
      font-weight:700;margin-bottom:8px">🔍 Track Shipment</a>
    <div style="font-size:11px;color:#94a3b8;margin-top:8px">{track_url}</div>
    """

def _send(to: list, subject: str, html: str):
    if not resend.api_key or not to:
        print(f"[email] skipped — no API key or recipients. subject={subject}")
        return
    try:
        resend.Emails.send({"from": FROM_EMAIL, "to": to, "subject": subject, "html": html})
        print(f"[email] sent: {subject} → {to}")
    except Exception as e:
        print(f"[email] error: {e}")

# ── Public send functions ─────────────────────────────────────────────────

def send_etd_passed(s):
    subject = f"🚨 [{s.ref}] ETD passed — retrack to confirm departure"
    body = _shipment_body(s)
    html = _html_wrapper(
        f"{s.ref} — ETD Passed, Retrack Required",
        COLORS["warning"], "🚨", body
    )
    _send(TEAM_EMAILS, subject, html)

def send_eta_reached_team(s):
    subject = f"🛬 [{s.ref}] ETA reached — check arrival at {s.pod or 'destination'}"
    body = _shipment_body(s)
    html = _html_wrapper(
        f"{s.ref} — ETA Reached, Check Arrival",
        COLORS["danger"], "🛬", body
    )
    _send(TEAM_EMAILS, subject, html)

def send_eta_reached_client(s):
    if not s.client_email: return
    track_url = f"{APP_URL}/track/{s.ref}"
    client_body = f"""
    <p style="font-size:15px;color:#0f172a;margin-bottom:20px">
      Dear {s.client or "Customer"},
    </p>
    <p style="font-size:14px;color:#475569;line-height:1.7;margin-bottom:24px">
      We're pleased to inform you that your shipment has reached its destination.
      Please coordinate with your local agent for customs clearance and delivery.
    </p>
    {_shipment_body(s)}
    """
    html = _html_wrapper(
        f"Your shipment {s.ref} has arrived at {s.pod or 'destination'}",
        COLORS["success"], "🛬", client_body
    )
    _send([s.client_email], f"Your shipment {s.ref} has arrived", html)

def send_arriving_soon_team(s, days: int):
    subject = f"📅 [{s.ref}] Arriving in {days} day{'s' if days>1 else ''} at {s.pod or 'destination'}"
    body = _shipment_body(s)
    html = _html_wrapper(
        f"{s.ref} — Arriving in {days} day{'s' if days>1 else ''}",
        COLORS["info"], "📅", body
    )
    _send(TEAM_EMAILS, subject, html)

def send_arriving_soon_client(s, days: int):
    if not s.client_email: return
    client_body = f"""
    <p style="font-size:15px;color:#0f172a;margin-bottom:20px">
      Dear {s.client or "Customer"},
    </p>
    <p style="font-size:14px;color:#475569;line-height:1.7;margin-bottom:24px">
      Your shipment is expected to arrive at <strong>{s.pod or "destination"}</strong>
      in <strong>{days} day{'s' if days>1 else ''}</strong>.
      Please ensure all customs documentation is ready.
    </p>
    {_shipment_body(s)}
    """
    html = _html_wrapper(
        f"Your shipment {s.ref} arrives in {days} day{'s' if days>1 else ''}",
        COLORS["info"], "📅", client_body
    )
    _send([s.client_email], f"Your shipment {s.ref} arrives in {days} day{'s' if days>1 else ''}", html)

def send_stuffing_date_reached(s):
    extra = '''<tr>
      <td style="padding:8px 0;font-size:12px;color:#64748b;font-weight:600;width:130px">Stuffing Date</td>
      <td style="padding:8px 0;font-size:13px;color:#f59e0b;font-weight:700">''' + (s.stuffing_date or "—") + '''</td>
    </tr>'''
    subject = f"📦 [{s.ref}] EXW Stuffing date reached — confirm loading"
    body = _shipment_body(s, extra)
    html = _html_wrapper(
        f"{s.ref} — EXW Stuffing Date Reached",
        COLORS["warning"], "📦", body
    )
    _send(TEAM_EMAILS, subject, html)
