from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel
from typing import Optional, Dict, Any
from backend.core.database import get_db_connection
from backend.core.security import verify_password, create_access_token, decode_access_token

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    user: Dict[str, Any]

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

def get_current_user(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> Dict[str, Any]:
    raw_token = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split(" ")[1]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(status_code=401, detail="Authentication credentials missing or invalid")
    payload = decode_access_token(raw_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Session expired or invalid token")
    return payload

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (req.username.strip(),)).fetchone()
    conn.close()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    must_change = bool(row["must_change_password"]) if "must_change_password" in row.keys() else False

    user_data = {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "must_change_password": must_change
    }
    token = create_access_token(user_data)
    return LoginResponse(access_token=token, must_change_password=must_change, user=user_data)

@router.post("/change-password")
def change_password(req: ChangePasswordRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid user token payload")

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters long")

    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()

    if not row or not verify_password(req.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password verification failed")

    from backend.core.database import update_user_password
    update_user_password(user_id, req.new_password)
    return {"ok": True, "message": "Password changed successfully"}

@router.get("/me")
def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    return {"user": user}

@router.post("/logout")
def logout():
    return {"ok": True, "message": "Logged out successfully"}
