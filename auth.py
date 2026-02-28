import os, bcrypt
from datetime import datetime, timedelta
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Use PyJWT
try:
    import jwt
except ImportError:
    from jose import jwt

SECRET   = os.getenv("JWT_SECRET", "freighttrack_secret_2026")
ALG      = "HS256"
EXPIRE_H = 24
bearer   = HTTPBearer(auto_error=False)

def hash_password(pw: str) -> str:
    """Always returns a clean utf-8 string"""
    hashed = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")

def verify_password(pw: str, hashed: str) -> bool:
    """Handles both str and bytes stored hashes"""
    try:
        pw_bytes     = pw.encode("utf-8")
        hashed_bytes = hashed.encode("utf-8") if isinstance(hashed, str) else hashed
        return bcrypt.checkpw(pw_bytes, hashed_bytes)
    except Exception as e:
        print(f"verify_password error: {e}")
        return False

def create_token(user_id: int, role: str, name: str) -> str:
    payload = {
        "sub":  str(user_id),
        "role": role,
        "name": name,
        "exp":  datetime.utcnow() + timedelta(hours=EXPIRE_H),
    }
    return jwt.encode(payload, SECRET, algorithm=ALG)

def decode_token(token: str) -> dict:
    try:
        data = jwt.decode(token, SECRET, algorithms=[ALG])
        # PyJWT returns dict directly; python-jose also returns dict
        return data
    except Exception as e:
        raise HTTPException(401, f"Invalid token: {e}")

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not creds:
        raise HTTPException(401, "Not authenticated")
    return decode_token(creds.credentials)

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user
