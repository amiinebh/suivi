from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Float
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    name = Column(String)
    role = Column(String, default="cs")
    hashed_pw = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String, unique=True, index=True)
    ref2 = Column(String, index=True, nullable=True) 
    booking_no = Column(String, index=True, nullable=True)
    quotation_number = Column(String, index=True, nullable=True)
    mode = Column(String, default="Ocean")
    carrier = Column(String, nullable=True)
    client = Column(String, nullable=True)
    client_email = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    pol = Column(String, nullable=True)
    pod = Column(String, nullable=True)
    etd = Column(String, nullable=True)
    eta = Column(String, nullable=True)
    status = Column(String, default="Pending")
    vessel = Column(String, nullable=True)
    direction = Column(String, nullable=True)
    incoterm = Column(String, nullable=True)
    stuffing_date = Column(String, nullable=True)
    agent = Column(String, nullable=True)
    shipsgo_id = Column(String, nullable=True)
    last_tracked = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    events = relationship("Event", back_populates="shipment", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="shipment", cascade="all, delete-orphan")
    containers = relationship("Container", back_populates="shipment", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"))
    timestamp = Column(String)
    location = Column(String, nullable=True)
    description = Column(String)
    status = Column(String, nullable=True)
    shipment = relationship("Shipment", back_populates="events")

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"))
    author = Column(String)
    text = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    shipment = relationship("Shipment", back_populates="comments")

class Container(Base):
    __tablename__ = "containers"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"))
    container_no = Column(String)
    size_type = Column(String, nullable=True)
    seal_no = Column(String, nullable=True)
    weight = Column(String, nullable=True)
    shipment = relationship("Shipment", back_populates="containers")

class EmailLog(Base):
    __tablename__ = "email_logs"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, index=True)
    sent_to = Column(String)
    sent_by = Column(String)
    subject = Column(String)
    body = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)

class Quote(Base):
    __tablename__ = "quotes"
    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String, unique=True, index=True)
    client = Column(String, nullable=False)
    email = Column(String, nullable=False)
    pol = Column(String, nullable=False)
    pod = Column(String, nullable=False)
    mode = Column(String, default="Ocean")
    rate = Column(Float, nullable=False)
    totalTeu = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    status = Column(String, default="pending")
    containers = Column(Text, nullable=True)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())
