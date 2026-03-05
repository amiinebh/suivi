from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class Shipment(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String, unique=True, index=True)
    ref2 = Column(String, nullable=True)
    bookingno = Column(String, nullable=True)
    mode = Column(String, default="Ocean")
    carrier = Column(String, nullable=True)
    vessel = Column(String, nullable=True)
    pol = Column(String, nullable=True)
    pod = Column(String, nullable=True)
    eta = Column(String, nullable=True)
    etd = Column(String, nullable=True)
    status = Column(String, default="Pending")
    client = Column(String, nullable=True)
    clientemail = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    shipsgoid = Column(Integer, nullable=True)
    quotationnumber = Column(String, nullable=True)
    lasttracked = Column(String, nullable=True)
    createdat = Column(String, default=lambda: datetime.utcnow().isoformat())
    direction = Column(String, nullable=True)
    incoterm = Column(String, nullable=True)
    stuffingdate = Column(String, nullable=True)
    agent = Column(String, nullable=True)
    shipper = Column(String, nullable=True)
    consignee = Column(String, nullable=True)
    teu = Column(String, nullable=True)
    events = relationship("ShipmentEvent", back_populates="shipment", cascade="all, delete")
    comments = relationship("ShipmentComment", back_populates="shipment", cascade="all, delete")
    containers = relationship("Container", back_populates="shipment", cascade="all, delete")


class ShipmentEvent(Base):
    __tablename__ = "shipmentevents"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"))
    timestamp = Column(String, default=lambda: datetime.utcnow().isoformat())
    location = Column(String, nullable=True)
    description = Column(String, nullable=True)
    status = Column(String, nullable=True)
    shipment = relationship("Shipment", back_populates="events")


class ShipmentComment(Base):
    __tablename__ = "shipmentcomments"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"))
    timestamp = Column(String, default=lambda: datetime.utcnow().isoformat())
    author = Column(String, default="Agent")
    text = Column(Text)
    shipment = relationship("Shipment", back_populates="comments")


class Container(Base):
    __tablename__ = "containers"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"))
    containerno = Column(String, nullable=False)
    sealno = Column(String, nullable=True)
    sizetype = Column(String, nullable=True)
    weight = Column(String, nullable=True)
    createdat = Column(String, default=lambda: datetime.utcnow().isoformat())
    shipment = relationship("Shipment", back_populates="containers")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, default="cs")
    hashedpw = Column(String, nullable=False)
    isactive = Column(Boolean, default=True)
    createdat = Column(String, default=lambda: datetime.utcnow().isoformat())


class AlertLog(Base):
    __tablename__ = "alertlogs"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, nullable=False)
    sentdate = Column(String, nullable=False)
    createdat = Column(String, default=lambda: datetime.utcnow().isoformat())


class Quotation(Base):
    __tablename__ = "quotations"
    id = Column(Integer, primary_key=True, index=True)
    ref = Column(String, unique=True, index=True, nullable=False)
    mode = Column(String, default="Ocean")
    client = Column(String, nullable=True)
    clientemail = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    pol = Column(String, nullable=True)
    pod = Column(String, nullable=True)
    etd = Column(String, nullable=True)
    eta = Column(String, nullable=True)
    bookingno = Column(String, nullable=True)
    incoterm = Column(String, nullable=True)
    status = Column(String, default="Pending")
    note = Column(Text, nullable=True)
    shipper = Column(String, nullable=True)
    consignee = Column(String, nullable=True)
    createdat = Column(String, default=lambda: datetime.utcnow().isoformat())
    updatedat = Column(String, default=lambda: datetime.utcnow().isoformat())
