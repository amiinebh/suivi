from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str; full_name: str; email: str; password: str
    role: Optional[str] = "operator"

class UserOut(BaseModel):
    id: int; username: str; full_name: str; email: str; role: str
    class Config: from_attributes = True

class ShipmentCreate(BaseModel):
    ref: str
    shipper: Optional[str] = ""; client: Optional[str] = ""
    mode: Optional[str] = "Ocean"; status: Optional[str] = "Pending"
    origin: Optional[str] = ""; dest: Optional[str] = ""
    carrier: Optional[str] = ""; etd: Optional[str] = ""; eta: Optional[str] = ""
    ref2: Optional[str] = ""; vessel: Optional[str] = ""
    goods: Optional[str] = ""; weight: Optional[str] = ""; notes: Optional[str] = ""

class ShipmentOut(ShipmentCreate):
    id: int
    last_tracked: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    class Config: from_attributes = True
