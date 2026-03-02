
@app.get("/api/suggest")
async def suggest(field: str = Query(...), q: str = Query(min_length=1)):
    if not q.strip():
        return []

    q = q.strip().lower()
    suggestions = []

    if field == "shipper":
        suggestions = [s.shipper for s in db.shipments if s.shipper and q in s.shipper.lower()]
    elif field == "consignee":
        suggestions = [s.consignee for s in db.shipments if s.consignee and q in s.consignee.lower()]
    elif field == "client":
        suggestions = [s.client for s in db.shipments if s.client and q in s.client.lower()]
    elif field == "carrier":
        suggestions = [s.carrier for s in db.shipments if s.carrier and q in s.carrier.lower()]
    elif field == "pol":
        ports = ["TNG", "AGP", "NTE", "LIS", "MAD", "BCN", "FAO", "ORY", "NYC", "LAX"]
        suggestions = [p for p in ports if q in p.lower()] + [s.pol for s in db.shipments if s.pol and q in s.pol.lower()]
    elif field == "pod":
        ports = ["TNG", "AGP", "NTE", "LIS", "BCN", "FAO", "ORY", "NYC", "LAX", "MIA"]
        suggestions = [p for p in ports if q in p.lower()] + [s.pod for s in db.shipments if s.pod and q in s.pod.lower()]

    # Dedupe + sort by match quality
    suggestions = list(dict.fromkeys(suggestions))
    suggestions.sort(key=lambda x: -len(get_close_matches([q], [x.lower()], n=1, cutoff=0.6)[0]) if get_close_matches([q], [x.lower()], n=1, cutoff=0.6) else 0)

    return suggestions[:10]

# Your existing main.py code here
