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

class EmailLog(Base):
    """Tracks every email sent to a client for a shipment."""
    __tablename__ = "email_logs"
    id          = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, nullable=False, index=True)
    sent_to     = Column(String, nullable=False)
    sent_by     = Column(String, nullable=True)   # username or "System"
    subject     = Column(String, nullable=True)
    sent_at     = Column(String, default=lambda: datetime.utcnow().isoformat())
