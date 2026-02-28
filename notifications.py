import os, requests as req

SENDGRID_KEY  = os.getenv("SENDGRID_API_KEY","")
FROM_EMAIL    = os.getenv("FROM_EMAIL","noreply@freighttrack.app")
APP_URL       = os.getenv("APP_URL","https://your-app.railway.app")

STATUS_LABELS = {
    "In Transit": "🚢 Your shipment is on the way!",
    "Delivered":  "✅ Your shipment has been delivered!",
    "Delayed":    "⚠️ Your shipment is delayed",
    "Customs":    "🛃 Your shipment is in customs",
    "Pending":    "⏳ Your shipment is being processed",
}

def send_status_email(shipment, new_status: str):
    """Send email to client when status changes."""
    if not SENDGRID_KEY or not shipment.client_email:
        return False
    subject = STATUS_LABELS.get(new_status, f"Shipment Update: {new_status}")
    portal_url = f"{APP_URL}/track/{shipment.ref}"
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#1a365d;padding:20px 28px;border-radius:10px 10px 0 0">
        <h2 style="color:#fff;margin:0">🚢 FreightTrack — Shipment Update</h2>
      </div>
      <div style="padding:28px;background:#fff;border:1px solid #e2e8f0;border-top:none">
        <p style="font-size:16px">Dear <strong>{shipment.client or 'Client'}</strong>,</p>
        <p style="font-size:15px">Your shipment status has been updated:</p>
        <div style="background:#f7fafc;border-radius:8px;padding:16px 20px;margin:16px 0">
          <table style="width:100%;font-size:14px">
            <tr><td style="color:#718096;padding:4px 0">Reference</td><td><strong>{shipment.ref}</strong></td></tr>
            <tr><td style="color:#718096;padding:4px 0">Container/AWB</td><td>{shipment.ref2 or '—'}</td></tr>
            <tr><td style="color:#718096;padding:4px 0">Route</td><td>{shipment.pol or '—'} → {shipment.pod or '—'}</td></tr>
            <tr><td style="color:#718096;padding:4px 0">ETA</td><td><strong>{shipment.eta or '—'}</strong></td></tr>
            <tr><td style="color:#718096;padding:4px 0">New Status</td><td><strong style="color:#2b6cb0">{new_status}</strong></td></tr>
          </table>
        </div>
        <a href="{portal_url}" style="display:inline-block;background:#2b6cb0;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:8px">
          📦 Track Your Shipment Live
        </a>
        <p style="margin-top:24px;font-size:12px;color:#a0aec0">
          This is an automated notification. Do not reply to this email.
        </p>
      </div>
    </div>"""
    payload = {
        "personalizations": [{"to": [{"email": shipment.client_email}]}],
        "from": {"email": FROM_EMAIL, "name": "FreightTrack"},
        "subject": subject,
        "content": [{"type": "text/html", "value": body_html}]
    }
    try:
        r = req.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {SENDGRID_KEY}","Content-Type":"application/json"},
            timeout=10
        )
        return r.status_code in (200, 202)
    except Exception as e:
        print(f"Email error: {e}")
        return False

def send_eta_change_email(shipment, old_eta: str, new_eta: str):
    if not SENDGRID_KEY or not shipment.client_email:
        return False
    portal_url = f"{APP_URL}/track/{shipment.ref}"
    body_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#744210;padding:20px 28px;border-radius:10px 10px 0 0">
        <h2 style="color:#fff;margin:0">📅 ETA Updated — FreightTrack</h2>
      </div>
      <div style="padding:28px;background:#fff;border:1px solid #e2e8f0;border-top:none">
        <p>Dear <strong>{shipment.client or 'Client'}</strong>,</p>
        <p>The estimated arrival for your shipment has changed:</p>
        <table style="width:100%;font-size:14px;background:#fffbeb;border-radius:8px;padding:14px">
          <tr><td style="color:#718096">Reference</td><td><strong>{shipment.ref}</strong></td></tr>
          <tr><td style="color:#718096">Container</td><td>{shipment.ref2 or '—'}</td></tr>
          <tr><td style="color:#718096">Route</td><td>{shipment.pol or '—'} → {shipment.pod or '—'}</td></tr>
          <tr><td style="color:#718096">Previous ETA</td><td><s style="color:#e53e3e">{old_eta}</s></td></tr>
          <tr><td style="color:#718096">New ETA</td><td><strong style="color:#276749">{new_eta}</strong></td></tr>
        </table>
        <a href="{portal_url}" style="display:inline-block;background:#744210;color:#fff;
          padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:16px">
          📦 Track Live
        </a>
      </div>
    </div>"""
    payload = {
        "personalizations": [{"to": [{"email": shipment.client_email}]}],
        "from": {"email": FROM_EMAIL, "name": "FreightTrack"},
        "subject": f"⚠️ ETA Updated: {shipment.ref} — now {new_eta}",
        "content": [{"type": "text/html", "value": body_html}]
    }
    try:
        r = req.post("https://api.sendgrid.com/v3/mail/send", json=payload,
            headers={"Authorization": f"Bearer {SENDGRID_KEY}", "Content-Type": "application/json"},
            timeout=10)
        return r.status_code in (200, 202)
    except Exception as e:
        print(f"ETA email error: {e}"); return False
