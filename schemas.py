from pydantic import BaseModel
from typing import Optional, List

class EventOut(BaseModel):
    id: int
    timestamp: str
    location: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
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

class ContainerOut(BaseModel):
    id: int
    container_no: str
    seal_no: Optional[str] = None
    size_type: Optional[str] = None
    weight: Optional[str] = None
    class Config: from_attributes = True

class ContainerCreate(BaseModel):
    container_no: str
    seal_no: Optional[str] = None
    size_type: Optional[str] = None
    weight: Optional[str] = None

class ShipmentCreate(BaseModel):
    ref: str
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: Optional[str] = "Ocean"
    carrier: Optional[str] = None
    vessel: Optional[str] = None
    client: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    client_email: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    status: Optional[str] = "Pending"
    note: Optional[str] = None
    quotation_number: Optional[str] = None
    incoterm: Optional[str] = None
    direction: Optional[str] = None
    agent: Optional[str] = None
    teu: Optional[int] = None

class ShipmentUpdate(BaseModel):
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: Optional[str] = None
    carrier: Optional[str] = None
    vessel: Optional[str] = None
    client: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    client_email: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    quotation_number: Optional[str] = None
    incoterm: Optional[str] = None
    direction: Optional[str] = None
    agent: Optional[str] = None
    teu: Optional[int] = None

class ShipmentOut(BaseModel):
    id: int
    ref: str
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: str
    carrier: Optional[str] = None
    vessel: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    eta: Optional[str] = None
    etd: Optional[str] = None
    status: str
    client: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    client_email: Optional[str] = None
    note: Optional[str] = None
    shipsgo_id: Optional[int] = None
    last_tracked: Optional[str] = None
    created_at: Optional[str] = None
    quotation_number: Optional[str] = None
    incoterm: Optional[str] = None
    direction: Optional[str] = None
    teu: Optional[int] = None
    events: List[EventOut] = []
    comments: List[CommentOut] = []
    containers: List[ContainerOut] = []
    class Config: from_attributes = True

class UserCreate(BaseModel):
    email: str
    name: str
    role: str = "cs"
    password: str

class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: Optional[str] = None
    class Config: from_attributes = True

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    role: str
    name: str
