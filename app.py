from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import os, sqlite3
from datetime import datetime
from io import BytesIO

APP_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(APP_DIR, 'static')
DB_PATH = os.path.join(APP_DIR, 'app.db')

app = FastAPI(title='FreightTrack Pro')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')

class ChargeIn(BaseModel):
    name: str
    amount: Optional[str] = None
    currency: Optional[str] = 'USD'
    unit: Optional[str] = ''
    note: Optional[str] = ''

class ContainerIn(BaseModel):
    qty: int
    ctype: str

class QuotationIn(BaseModel):
    ref: Optional[str] = None
    mode: Optional[str] = 'Ocean'
    client: Optional[str] = None
    clientemail: Optional[str] = None
    carrier: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    incoterm: Optional[str] = None
    validitydate: Optional[str] = None
    status: Optional[str] = 'Pending'
    note: Optional[str] = None
    currency: Optional[str] = 'USD'
    charges: List[ChargeIn] = []
    containers: List[ContainerIn] = []

def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS quotations (id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE, mode TEXT DEFAULT 'Ocean', client TEXT, client_email TEXT, carrier TEXT, pol TEXT, pod TEXT, incoterm TEXT, validity_date TEXT, status TEXT DEFAULT 'Pending', note TEXT, currency TEXT DEFAULT 'USD', created_at TEXT, updated_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS quotation_charges (id INTEGER PRIMARY KEY AUTOINCREMENT, quotation_id INTEGER NOT NULL, name TEXT NOT NULL, amount TEXT, currency TEXT, unit TEXT, note TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS quotation_containers (id INTEGER PRIMARY KEY AUTOINCREMENT, quotation_id INTEGER NOT NULL, qty INTEGER NOT NULL, ctype TEXT NOT NULL)")
    conn.commit(); conn.close()

def next_ref(conn):
    year = datetime.utcnow().year
    prefix = f'QUO-{year}-'
    rows = conn.execute('SELECT ref FROM quotations WHERE ref LIKE ?', (f'{prefix}%',)).fetchall()
    mx = 0
    for r in rows:
        try: mx = max(mx, int((r['ref'] or '').split('-')[-1]))
        except Exception: pass
    return f'{prefix}{str(mx+1).zfill(3)}'

def serialize_quotation(conn, row):
    qid = row['id']
    charges = [dict(x) for x in conn.execute('SELECT id,name,amount,currency,unit,note FROM quotation_charges WHERE quotation_id=? ORDER BY id ASC', (qid,)).fetchall()]
    containers = [dict(x) for x in conn.execute('SELECT id,qty,ctype FROM quotation_containers WHERE quotation_id=? ORDER BY id ASC', (qid,)).fetchall()]
    return {'id': row['id'], 'ref': row['ref'], 'mode': row['mode'], 'client': row['client'], 'clientemail': row['client_email'], 'carrier': row['carrier'], 'pol': row['pol'], 'pod': row['pod'], 'incoterm': row['incoterm'], 'validitydate': row['validity_date'], 'status': row['status'], 'note': row['note'], 'currency': row['currency'], 'createdat': row['created_at'], 'updatedat': row['updated_at'], 'charges': charges, 'containers': containers}

@app.on_event('startup')
def startup():
    os.makedirs(STATIC_DIR, exist_ok=True)
    init_db()

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/', response_class=HTMLResponse)
def root():
    with open(os.path.join(STATIC_DIR, 'index.html'), 'r', encoding='utf-8') as f:
        return HTMLResponse(f.read(), headers={'Cache-Control':'no-cache, no-store, must-revalidate', 'Pragma':'no-cache', 'Expires':'0'})

@app.get('/api/quotations/next-ref')
def api_next_ref():
    conn = db_conn(); ref = next_ref(conn); conn.close(); return {'ref': ref}

@app.get('/api/quotations/debug-schema')
def api_debug_schema():
    conn = db_conn(); q = [r['name'] for r in conn.execute('PRAGMA table_info(quotations)').fetchall()]; c = [r['name'] for r in conn.execute('PRAGMA table_info(quotation_charges)').fetchall()]; t = [r['name'] for r in conn.execute('PRAGMA table_info(quotation_containers)').fetchall()]; conn.close(); return {'quotations': q, 'quotation_charges': c, 'quotation_containers': t}

@app.get('/api/quotations')
def list_quotations(q: str = '', status: str = '', mode: str = ''):
    conn = db_conn(); sql = 'SELECT * FROM quotations WHERE 1=1'; params = []
    if q:
        sql += ' AND (ref LIKE ? OR client LIKE ? OR pol LIKE ? OR pod LIKE ?)'; like = f'%{q}%'; params += [like, like, like, like]
    if status and status != 'All Status': sql += ' AND status = ?'; params.append(status)
    if mode and mode != 'All Modes': sql += ' AND mode = ?'; params.append(mode)
    sql += ' ORDER BY id DESC'
    rows = conn.execute(sql, params).fetchall(); out = [serialize_quotation(conn, r) for r in rows]; conn.close(); return out

@app.get('/api/quotations/{qid}')
def get_quotation(qid: int):
    conn = db_conn(); row = conn.execute('SELECT * FROM quotations WHERE id=?', (qid,)).fetchone()
    if not row: conn.close(); raise HTTPException(404, 'Quotation not found')
    out = serialize_quotation(conn, row); conn.close(); return out

@app.post('/api/quotations')
def create_quotation(payload: QuotationIn):
    conn = db_conn(); now = datetime.utcnow().isoformat(); ref = (payload.ref or '').strip() or next_ref(conn); cur = conn.cursor()
    cur.execute('INSERT INTO quotations (ref, mode, client, client_email, carrier, pol, pod, incoterm, validity_date, status, note, currency, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (ref, payload.mode or 'Ocean', payload.client, payload.clientemail, payload.carrier, payload.pol, payload.pod, payload.incoterm, payload.validitydate, payload.status or 'Pending', payload.note, payload.currency or 'USD', now, now))
    qid = cur.lastrowid
    for ch in payload.charges:
        if (ch.name or '').strip(): cur.execute('INSERT INTO quotation_charges (quotation_id, name, amount, currency, unit, note) VALUES (?, ?, ?, ?, ?, ?)', (qid, ch.name.strip(), ch.amount, ch.currency or 'USD', ch.unit or '', ch.note or ''))
    for ct in payload.containers:
        if ct.qty and ct.ctype: cur.execute('INSERT INTO quotation_containers (quotation_id, qty, ctype) VALUES (?, ?, ?)', (qid, int(ct.qty), ct.ctype))
    conn.commit(); row = conn.execute('SELECT * FROM quotations WHERE id=?', (qid,)).fetchone(); out = serialize_quotation(conn, row); conn.close(); return out

@app.patch('/api/quotations/{qid}')
@app.put('/api/quotations/{qid}')
def update_quotation(qid: int, payload: QuotationIn):
    conn = db_conn(); now = datetime.utcnow().isoformat(); cur = conn.cursor()
    cur.execute('UPDATE quotations SET mode=?, client=?, client_email=?, carrier=?, pol=?, pod=?, incoterm=?, validity_date=?, status=?, note=?, currency=?, updated_at=? WHERE id=?', (payload.mode or 'Ocean', payload.client, payload.clientemail, payload.carrier, payload.pol, payload.pod, payload.incoterm, payload.validitydate, payload.status or 'Pending', payload.note, payload.currency or 'USD', now, qid))
    cur.execute('DELETE FROM quotation_charges WHERE quotation_id=?', (qid,)); cur.execute('DELETE FROM quotation_containers WHERE quotation_id=?', (qid,))
    for ch in payload.charges:
        if (ch.name or '').strip(): cur.execute('INSERT INTO quotation_charges (quotation_id, name, amount, currency, unit, note) VALUES (?, ?, ?, ?, ?, ?)', (qid, ch.name.strip(), ch.amount, ch.currency or 'USD', ch.unit or '', ch.note or ''))
    for ct in payload.containers:
        if ct.qty and ct.ctype: cur.execute('INSERT INTO quotation_containers (quotation_id, qty, ctype) VALUES (?, ?, ?)', (qid, int(ct.qty), ct.ctype))
    conn.commit(); row = conn.execute('SELECT * FROM quotations WHERE id=?', (qid,)).fetchone()
    if not row: conn.close(); raise HTTPException(404, 'Quotation not found')
    out = serialize_quotation(conn, row); conn.close(); return out

@app.delete('/api/quotations/{qid}')
def delete_quotation(qid: int):
    conn = db_conn(); conn.execute('DELETE FROM quotation_charges WHERE quotation_id=?', (qid,)); conn.execute('DELETE FROM quotation_containers WHERE quotation_id=?', (qid,)); conn.execute('DELETE FROM quotations WHERE id=?', (qid,)); conn.commit(); conn.close(); return {'ok': True}

@app.get('/api/quotations/{qid}/pdf')
def quotation_pdf(qid: int):
    conn = db_conn(); row = conn.execute('SELECT * FROM quotations WHERE id=?', (qid,)).fetchone()
    if not row: conn.close(); raise HTTPException(404, 'Quotation not found')
    q = serialize_quotation(conn, row); conn.close()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    buf = BytesIO(); doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet(); title = ParagraphStyle('title', parent=styles['Heading1'], alignment=TA_CENTER, textColor=colors.HexColor('#21808D'), fontSize=20); head = ParagraphStyle('head', parent=styles['Heading2'], textColor=colors.HexColor('#21808D'), fontSize=12)
    story = [Paragraph('FREIGHT QUOTATION', title), Spacer(1, 5*mm), Paragraph(f'<b>Quotation Ref:</b> {q["ref"]}<br/><b>Valid Until:</b> {q["validitydate"] or "N/A"}', styles['Normal']), Spacer(1, 4*mm), Paragraph('SHIPMENT DETAILS', head)]
    table = Table([['Client', q['client'] or 'N/A', 'Mode', q['mode'] or 'N/A'], ['POL', q['pol'] or 'N/A', 'POD', q['pod'] or 'N/A'], ['Carrier', q['carrier'] or 'N/A', 'Currency', q['currency'] or 'USD'], ['Incoterm', q['incoterm'] or 'N/A', 'Status', q['status'] or 'Pending']], colWidths=[28*mm, 62*mm, 28*mm, 62*mm])
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(0,-1),colors.whitesmoke),('BACKGROUND',(2,0),(2,-1),colors.whitesmoke)])); story.append(table)
    if q['containers']:
        story += [Spacer(1,4*mm), Paragraph('CONTAINERS', head)]
        ct = Table([['Qty','Type']] + [[str(c['qty']), c['ctype']] for c in q['containers']], colWidths=[30*mm, 150*mm])
        ct.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)])); story.append(ct)
    story += [Spacer(1,4*mm), Paragraph('CHARGES', head)]
    rows = [['Description','Amount','Currency','Unit']]; totals = {}
    for c in q['charges']:
        rows.append([c['name'], c['amount'] or '0', c['currency'] or 'USD', c['unit'] or ''])
        try: totals[c['currency'] or 'USD'] = totals.get(c['currency'] or 'USD', 0) + float(c['amount'] or 0)
        except Exception: pass
    if len(rows) == 1: rows.append(['No charges', '0', q['currency'] or 'USD', ''])
    ch = Table(rows, colWidths=[80*mm, 30*mm, 30*mm, 40*mm])
    ch.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#21808D')),('TEXTCOLOR',(0,0),(-1,0),colors.white)])); story.append(ch)
    if totals: story += [Spacer(1,3*mm), Paragraph('<b>Total:</b> ' + ' + '.join([f'{v:,.2f} {k}' for k,v in totals.items()]), styles['Normal'])]
    if q['note']: story += [Spacer(1,4*mm), Paragraph('NOTES', head), Paragraph((q['note'] or '').replace('\n','<br/>'), styles['Normal'])]
    doc.build(story); buf.seek(0)
    return Response(content=buf.getvalue(), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename=quotation_{q["ref"]}.pdf'})

@app.exception_handler(Exception)
async def all_errors(request, exc):
    return JSONResponse(status_code=500, content={'detail': f'{type(exc).__name__}: {str(exc)}'})
