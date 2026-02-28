from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String, unique=True, index=True, nullable=False)
    full_name       = Column(String, nullable=False)
    email           = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role            = Column(String, default="operator")
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

class Shipment(Base):
    __tablename__ = "shipments"
    id           = Column(Integer, primary_key=True, index=True)
    ref          = Column(String, unique=True, index=True, nullable=False)
    shipper      = Column(String)
    client       = Column(String)
    mode         = Column(String)
    status       = Column(String)
    origin       = Column(String)
    dest         = Column(String)
    carrier      = Column(String)
    etd          = Column(String)
    eta          = Column(String)
    ref2         = Column(String)
    vessel       = Column(String)
    goods        = Column(String)
    weight       = Column(String)
    notes        = Column(String)
    last_tracked = Column(String)
    created_by   = Column(Integer, ForeignKey("users.id"))
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())
