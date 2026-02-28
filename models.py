from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class Shipment(Base):
    __tablename__ = "shipments"
    id            = Column(Integer, primary_key=True, index=True)
    ref           = Column(String, unique=True, index=True)   # internal ref
    ref2          = Column(String, nullable=True)              # container/AWB
    booking_no    = Column(String, nullable=True)
    mode          = Column(String, default="Ocean")            # Ocean | Air
    carrier       = Column(String, nullable=True)
    vessel        = Column(String, nullable=True)
    pol           = Column(String, nullable=True)              # port of loading
    pod           = Column(String, nullable=True)              # port of discharge
    eta           = Column(String, nullable=True)
    etd           = Column(String, nullable=True)
    status        = Column(String, default="Pending")
    client        = Column(String, nullable=True)
    note          = Column(Text, nullable=True)
    shipsgo_id    = Column(Integer, nullable=True)
    last_tracked  = Column(String, nullable=True)
    created_at    = Column(String, default=lambda: datetime.utcnow().isoformat())
    events        = relationship("ShipmentEvent", back_populates="shipment", cascade="all, delete")

class ShipmentEvent(Base):
    __tablename__ = "shipment_events"
    id            = Column(Integer, primary_key=True, index=True)
    shipment_id   = Column(Integer, ForeignKey("shipments.id"))
    timestamp     = Column(String, default=lambda: datetime.utcnow().isoformat())
    location      = Column(String, nullable=True)
    description   = Column(String, nullable=True)
    status        = Column(String, nullable=True)
    shipment      = relationship("Shipment", back_populates="events")
