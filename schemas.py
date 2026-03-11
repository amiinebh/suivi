from pydantic import BaseModel, field_validator, EmailStr
from typing import Optional
import re as _re

def _str(max_len: int, val):
    if val is None: return val
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
    quotationnumber: Optional[str] = None

    @field_validator("ref")
    @classmethod
    def val_ref(cls, v):
        v = str(v).strip()
        if not v: raise ValueError("ref is required")
        if len(v) > 100: raise ValueError("ref too long (max 100)")
        return v

    @field_validator("carrier","shipper","consignee","client","pol","pod","booking_no","ref2","mode","incoterm","status", mode="before")
    @classmethod
    def val_short(cls, v): return _str(200, v)

    @field_validator("note","notes", mode="before")
    @classmethod
    def val_note(cls, v): return _str(2000, v)

    @field_validator("client_email", mode="before")
    @classmethod
    def val_email(cls, v):
        if not v: return None
        v = str(v).strip()
        if v and not _re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", v):
            raise ValueError("Invalid email format")
        return _str(254, v)

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
