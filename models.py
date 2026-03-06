from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class Shipment(Base):
    __tablename__ = "shipments"
    id            = Column(Integer, primary_key=True, index=True)
    ref           = Column(String, unique=True, index=True)
    ref2          = Column(String, nullable=True)       # container / AWB
    booking_no    = Column(String, nullable=True)
    mode          = Column(String, default="Ocean")     # Ocean | Air
    carrier       = Column(String, nullable=True)
    vessel        = Column(String, nullable=True)
    pol           = Column(String, nullable=True)
    pod           = Column(String, nullable=True)
    eta           = Column(String, nullable=True)
    etd           = Column(String, nullable=True)
    status        = Column(String, default="Pending")
    client        = Column(String, nullable=True)
    client_email  = Column(String, nullable=True)       # for email alerts
    note          = Column(Text, nullable=True)
    shipsgo_id    = Column(Integer, nullable=True)
    quotation_number = Column(String, nullable=True)
    last_tracked  = Column(String, nullable=True)
    created_at    = Column(String, default=lambda: datetime.utcnow().isoformat())
    direction     = Column(String, nullable=True)   # Export | Import
    incoterm      = Column(String, nullable=True)   # EXW, FOB, CIF…
    stuffing_date = Column(String, nullable=True)   # only for EXW
    agent         = Column(String, nullable=True)   # Import agent
    events        = relationship("ShipmentEvent", back_populates="shipment", cascade="all, delete")
    comments      = relationship("ShipmentComment", back_populates="shipment", cascade="all, delete")
    containers    = relationship("Container", back_populates="shipment", cascade="all, delete")

class ShipmentEvent(Base):
    __tablename__ = "shipment_events"
    id            = Column(Integer, primary_key=True, index=True)
    shipment_id   = Column(Integer, ForeignKey("shipments.id"))
    timestamp     = Column(String, default=lambda: datetime.utcnow().isoformat())
    location      = Column(String, nullable=True)
    description   = Column(String, nullable=True)
    status        = Column(String, nullable=True)
    shipment      = relationship("Shipment", back_populates="events")

class ShipmentComment(Base):
    __tablename__ = "shipment_comments"
    id            = Column(Integer, primary_key=True, index=True)
    shipment_id   = Column(Integer, ForeignKey("shipments.id"))
    timestamp     = Column(String, default=lambda: datetime.utcnow().isoformat())
    author        = Column(String, default="Agent")
    text          = Column(Text)
    shipment      = relationship("Shipment", back_populates="comments")


class Container(Base):
    __tablename__ = "containers"
    id            = Column(Integer, primary_key=True, index=True)
    shipment_id   = Column(Integer, ForeignKey("shipments.id"))
    container_no  = Column(String, nullable=False)  # MSCU1234567
    seal_no       = Column(String, nullable=True)
    size_type     = Column(String, nullable=True)   # 20GP, 40HC, 40RF
    weight        = Column(String, nullable=True)
    created_at    = Column(String, default=lambda: datetime.utcnow().isoformat())
    shipment      = relationship("Shipment", back_populates="containers")

class User(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True, index=True)
    email      = Column(String, unique=True, index=True, nullable=False)
    name       = Column(String, nullable=False)
    role       = Column(String, default="cs")        # "admin" | "cs"
    hashed_pw  = Column(String, nullable=False)
    is_active  = Column(Boolean, default=True)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())

class AlertLog(Base):
    """Tracks which alert emails have been sent to avoid duplicates."""
    __tablename__ = "alert_logs"
    id        = Column(Integer, primary_key=True, index=True)
    key       = Column(String, nullable=False)    # e.g. "eta_reached_team:42:2026-03-05"
    sent_date = Column(String, nullable=False)    # ISO date "2026-03-01"
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())



class Quotation(Base):
    __tablename__ = "quotations"
    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String, unique=True, index=True, nullable=False)
    mode = Column(String, default="Ocean")
    client = Column(String, nullable=True)
    client_email = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    pol = Column(String, nullable=True)
    pod = Column(String, nullable=True)
    incoterm = Column(String, nullable=True)
    validity_date = Column(String, nullable=True)
    status = Column(String, default="Pending")
    note = Column(Text, nullable=True)
    currency = Column(String, default="USD")
    created_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)

class QuotationCharge(Base):
    __tablename__ = "quotation_charges"
    id = Column(Integer, primary_key=True, index=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    name = Column(String, nullable=False)
    amount = Column(String, nullable=True)
    currency = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    note = Column(String, nullable=True)

class QuotationContainer(Base):
    __tablename__ = "quotation_containers"
    id = Column(Integer, primary_key=True, index=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    qty = Column(Integer, nullable=False)
    ctype = Column(String, nullable=False)
