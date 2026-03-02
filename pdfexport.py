import io

def generate_shipment_pdf(s):
    return b"%PDF-1.4\n1 0 obj\n<< /Title (Shipment) >>\nendobj\n"

def generate_dashboard_pdf(stats, ships):
    return b"%PDF-1.4\n1 0 obj\n<< /Title (Dashboard) >>\nendobj\n"

def generate_kpi_report_pdf(stats, ships):
    return b"%PDF-1.4\n1 0 obj\n<< /Title (KPI) >>\nendobj\n"
