from pydantic import BaseModel, field_validator
from typing import Optional, List
import re as _re


def _str(max_len, val):
    if val is None:
        return val
    val = str(val).strip()
    if len(val) > max_len:
        raise ValueError(f"Value exceeds maximum length of {max_len}")
    return val or None


class ShipmentCreate(BaseModel):
    ref: str
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: Optional[str] = "Ocean"
    carrier: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    client: Optional[str] = None
    client_email: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    status: Optional[str] = "Pending"
    note: Optional[str] = None
    notes: Optional[str] = None
    incoterm: Optional[str] = None
    teu: Optional[float] = None
    quotation_number: Optional[str] = None

    @field_validator("ref")
    @classmethod
    def val_ref(cls, v):
        v = str(v).strip()
        if not v:
            raise ValueError("ref is required")
        if len(v) > 100:
            raise ValueError("ref too long (max 100)")
        return v

    @field_validator("carrier", "shipper", "consignee", "client",
                     "pol", "pod", "booking_no", "ref2", "mode",
                     "incoterm", "status", mode="before")
    @classmethod
    def val_short(cls, v):
        return _str(200, v)

    @field_validator("note", "notes", mode="before")
    @classmethod
    def val_note(cls, v):
        return _str(2000, v)

    @field_validator("client_email", mode="before")
    @classmethod
    def val_email(cls, v):
        if not v:
            return None
        v = str(v).strip()
        if v and not _re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
            raise ValueError("Invalid email format")
        return _str(254, v)


class ShipmentUpdate(BaseModel):
    ref: Optional[str] = None
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: Optional[str] = None
    carrier: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    client: Optional[str] = None
    client_email: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None
    notes: Optional[str] = None
    incoterm: Optional[str] = None
    teu: Optional[float] = None
    vessel: Optional[str] = None
    quotation_number: Optional[str] = None


class EventOut(BaseModel):
    id: int
    shipment_id: int
    status: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    timestamp: Optional[str] = None
    class Config:
        from_attributes = True


class CommentOut(BaseModel):
    id: int
    shipment_id: int
    author: Optional[str] = None
    text: Optional[str] = None
    timestamp: Optional[str] = None
    class Config:
        from_attributes = True


class CommentCreate(BaseModel):
    author: Optional[str] = None
    text: str


class ContainerOut(BaseModel):
    id: int
    shipment_id: int
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    size_type: Optional[str] = None
    weight: Optional[str] = None
    created_at: Optional[str] = None
    class Config:
        from_attributes = True


class ContainerCreate(BaseModel):
    container_no: Optional[str] = None
    seal_no: Optional[str] = None
    size_type: Optional[str] = None
    weight: Optional[str] = None


class ShipmentOut(BaseModel):
    id: int
    ref: str
    ref2: Optional[str] = None
    booking_no: Optional[str] = None
    mode: str = "Ocean"
    carrier: Optional[str] = None
    vessel: Optional[str] = None
    pol: Optional[str] = None
    pod: Optional[str] = None
    eta: Optional[str] = None
    etd: Optional[str] = None
    status: str = "Pending"
    client: Optional[str] = None
    client_email: Optional[str] = None
    note: Optional[str] = None
    notes: Optional[str] = None
    incoterm: Optional[str] = None
    teu: Optional[float] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    direction: Optional[str] = None
    quotation_number: Optional[str] = None
    shipsgo_id: Optional[int] = None
    last_tracked: Optional[str] = None
    created_at: Optional[str] = None
    events: List[EventOut] = []
    comments: List[CommentOut] = []
    containers: List[ContainerOut] = []
    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "agent"


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Optional[dict] = None
