from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.db import supabase

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(subject: str, extra: dict[str, Any] | None = None, token_type: str = "admin") -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.admin_token_expire_minutes)).timestamp()),
        "type": token_type,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_admin_by_email(email: str) -> dict | None:
    result = supabase.table("admin_users").select("*").eq("email", email.lower()).limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None


def get_admin_by_id(admin_id: str) -> dict | None:
    result = supabase.table("admin_users").select("*").eq("id", admin_id).limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None


def get_client_by_email(email: str) -> dict | None:
    result = supabase.table("users").select("*").eq("email", email.lower()).limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None


def get_client_by_id(client_id: str) -> dict | None:
    result = supabase.table("users").select("*").eq("id", client_id).limit(1).execute()
    rows = result.data or []
    return rows[0] if rows else None


async def get_current_client(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client login required")

    settings = get_settings()
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "client":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        client_id = payload.get("sub")
        if not client_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    client = get_client_by_id(client_id)
    if not client or not client.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client account inactive")
    return client


def ensure_default_admin() -> None:
    """Create the first admin from environment variables when admin_users is empty."""
    settings = get_settings()
    try:
        existing = supabase.table("admin_users").select("id").limit(1).execute().data or []
        if existing:
            return
        supabase.table("admin_users").insert({
            "email": settings.default_admin_email.lower(),
            "password_hash": hash_password(settings.default_admin_password),
            "role": "super_admin",
        }).execute()
    except Exception as exc:
        # Do not stop app boot if schema has not been run yet. The health endpoint should still work.
        print(f"Default admin bootstrap skipped: {exc}")


async def get_current_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin login required")

    settings = get_settings()
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != "admin":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        admin_id = payload.get("sub")
        if not admin_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    admin = get_admin_by_id(admin_id)
    if not admin or not admin.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin account inactive")
    return admin
