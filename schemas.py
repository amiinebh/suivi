from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "cs"

class CommentCreate(BaseModel):
    text: str

class CommentOut(BaseModel):
    id: int
    author: str
    text: str
    timestamp: datetime
    class Config:
        from_attributes = True

class EventOut(BaseModel):
    timestamp: str
    location: Optional[str]
    description: str
    status: Optional[str]
    class Config:
        from_attributes = True

class ContainerOut(BaseModel):
    id: int
    container_no: str
    size_type: Optional[str]
    seal_no: Optional[str]
    weight: Optional[str]
    class Config:
        from_attributes = True

class ShipmentCreate(BaseModel):
    ref: str
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: str = "Ocean"
    carrier: Optional[str] = None
    client: Optional[str] = None
    client_email: Optional[str] = None
    note: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    quotation_number: Optional[str] = None
    status: str = "Pending"
    vessel: Optional[str] = None
    direction: Optional[str] = None
    incoterm: Optional[str] = None
    stuffing_date: Optional[str] = None
    agent: Optional[str] = None

class ShipmentUpdate(BaseModel):
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: Optional[str] = None
    carrier: Optional[str] = None
    client: Optional[str] = None
    client_email: Optional[str] = None
    note: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    quotation_number: Optional[str] = None
    status: Optional[str] = None
    vessel: Optional[str] = None
    direction: Optional[str] = None
    incoterm: Optional[str] = None
    stuffing_date: Optional[str] = None
    agent: Optional[str] = None

class ShipmentOut(BaseModel):
    id: int
    ref: str
    ref2: Optional[str]
    booking_no: Optional[str]
    quotation_number: Optional[str]
    mode: str
    carrier: Optional[str]
    client: Optional[str]
    client_email: Optional[str]
    note: Optional[str]
    pol: Optional[str]
    pod: Optional[str]
    etd: Optional[str]
    eta: Optional[str]
    status: str
    vessel: Optional[str]
    direction: Optional[str]
    incoterm: Optional[str]
    stuffing_date: Optional[str]
    agent: Optional[str]
    shipsgo_id: Optional[str]
    last_tracked: Optional[str]
    created_at: datetime
    events: List[EventOut] = []
    comments: List[CommentOut] = []
    containers: List[ContainerOut] = []
    class Config:
        from_attributes = True
