FreightTrack Pro - Stable Quotation Build

This package is intended to be pushed directly to the GitHub main branch.

Included root files:
- app.py
- requirements.txt
- Procfile
- railway.json
- static/index.html

Expected Railway start command:
uvicorn app:app --host 0.0.0.0 --port $PORT

After pushing:
1. Wait for Railway auto-deploy.
2. Open /health
3. Open /
4. Test /api/quotations/debug-schema
