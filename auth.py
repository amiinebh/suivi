import os, bcrypt
from datetime import datetime, timedelta
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

try:
    import jwt
except ImportError:
    from jose import jwt

SECRET = os.getenv("JWT_SECRET", "freighttrack_secret_2026")
ALG = "HS256"
EXPIRE_H = 24
bearer = HTTPBearer(auto_error=False)

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"),
            hashed.encode("utf-8") if isinstance(hashed, str) else hashed)
    except Exception as e:
        print(f"verify_password error: {e}")
        return False

def create_token(user_id: int, role: str, name: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "name": name,
        "exp": datetime.utcnow() + timedelta(hours=EXPIRE_H),
    }
    return jwt.encode(payload, SECRET, algorithm=ALG)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALG])
    except Exception as e:
        raise HTTPException(401, f"Invalid token: {e}")

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    data = decode_token(creds.credentials)
    from database import SessionLocal
    import models as m
    db = SessionLocal()
    try:
        user = db.query(m.User).filter(m.User.id == int(data["sub"])).first()
        if not user or not user.isactive:          # ← fixed: isactive not is_active
            raise HTTPException(401, "Account deactivated")
    finally:
        db.close()
    return data

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user
