# FreightTrack Pro v36 - Quotation System

## Features
- ✅ Full quotation dashboard with approve/decline workflow
- ✅ PDF export for quotes (client-side generation)
- ✅ Email notifications (quote sent, approved)
- ✅ One-click convert quote → shipment
- ✅ Bulk import fix

## Setup

### 1. Environment Variables (.env)
```
DATABASE_URL=postgresql://user:pass@host:5432/dbname
SECRET_KEY=your-secret-key-here

# SMTP for emails
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-app-password
FROM_EMAIL=your-email@gmail.com
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Run Migrations
```bash
# Automatic on first run - creates quotes table
python -c "from database import engine; import models; models.Base.metadata.create_all(engine)"
```

### 4. Start Server
```bash
uvicorn main:app --reload --port 8000
```

### 5. Test Quotes Flow
1. Navigate to http://localhost:8000
2. Click "Quotes" in sidebar
3. New Quote → Fill form → Preview → Send Quote
4. Check email (client receives branded quote)
5. Approve quote → Create Shipment
6. Export PDF from quote card

## API Endpoints

### Quotes
- `GET /api/quotes?status=all` - List all quotes
- `POST /api/quotes` - Create quote (sends email)
- `PATCH /api/quotes/{id}` - Update status (approve/decline)

### Shipments (existing)
- All your current endpoints remain unchanged

## Email Templates
Located in `main.py`:
- `send_quote_email()` - Branded quote email with pricing table
- `send_quote_approved_email()` - Approval notification

## PDF Export
Client-side PDF generation using jsPDF:
- No backend required
- Professional branded layout
- Includes all quote details + pricing breakdown

## Database Schema
New table: `quotes`
- id, ref, client, email, pol, pod, mode
- rate, totalTeu, notes, status, containers (JSON)
- created_at

## Notes
- Quotes valid for 7 days (configurable)
- Status flow: pending → approved → shipment
- PDF downloads as `Quote_Q123456.pdf`
- Email requires SMTP config (Gmail/SendGrid/etc)
