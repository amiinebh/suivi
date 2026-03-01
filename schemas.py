from pydantic import BaseModel
from typing import Optional, List

class EventOut(BaseModel):
    id: int
    timestamp: str
    location: Optional[str]
    description: Optional[str]
    status: Optional[str]
    class Config: from_attributes = True

class CommentOut(BaseModel):
    id: int
    timestamp: str
    author: str
    text: str
    class Config: from_attributes = True

class CommentCreate(BaseModel):
    author: Optional[str] = "Agent"
    text: str

class ShipmentCreate(BaseModel):
    notes: Optional[str] = None
    consignee: Optional[str] = None
    shipper: Optional[str] = None
    quotation_number: Optional[str] = None
    ref: str
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: Optional[str] = "Ocean"
    carrier: Optional[str] = None
    client: Optional[str] = None
    client_email: Optional[str] = None
    note: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    status: Optional[str] = "Pending"

class ShipmentOut(BaseModel):
    id: int
    ref: str
    ref2: Optional[str]
    booking_no: Optional[str]
    mode: str
    carrier: Optional[str]
    vessel: Optional[str]
    pol: Optional[str]
    pod: Optional[str]
    eta: Optional[str]
    etd: Optional[str]
    status: str
    client: Optional[str]
    client_email: Optional[str]
    note: Optional[str]
    shipsgo_id: Optional[int]
    last_tracked: Optional[str]
    created_at: Optional[str]
    events: List[EventOut] = []
    comments: List[CommentOut] = []
    class Config: from_attributes = True

class ShipmentUpdate(BaseModel):
    notes: Optional[str] = None
    consignee: Optional[str] = None
    shipper: Optional[str] = None
    quotation_number: Optional[str] = None
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
    status: Optional[str] = None
    vessel: Optional[str] = None

class UserCreate(BaseModel):
    email: str
    name:  str
    role:  str = "cs"
    password: str

class UserOut(BaseModel):
    id:        int
    email:     str
    name:      str
    role:      str
    is_active: bool
    created_at: Optional[str] = None
    class Config: from_attributes = True

class LoginRequest(BaseModel):
    email:    str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    role:         str
    name:         str
