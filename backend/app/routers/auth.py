from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.auth import create_access_token, get_admin_by_email, get_client_by_email, get_current_admin, get_current_client, hash_password, verify_password
from app.db import supabase

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class ClientRegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8)
    company_name: str | None = None
    phone: str | None = None


class ClientLoginIn(BaseModel):
    email: EmailStr
    password: str


class ClientChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.post("/login")
def login(payload: LoginIn):
    admin = get_admin_by_email(payload.email)
    if not admin or not verify_password(payload.password, admin["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not admin.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin account inactive")
    token = create_access_token(admin["id"], {"email": admin["email"], "role": admin.get("role", "admin")})
    return {
        "access_token": token,
        "token_type": "bearer",
        "admin": {"id": admin["id"], "email": admin["email"], "role": admin.get("role", "admin")},
    }


@router.get("/me")
def me(admin: dict = Depends(get_current_admin)):
    return {"id": admin["id"], "email": admin["email"], "role": admin.get("role", "admin")}


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, admin: dict = Depends(get_current_admin)):
    if not verify_password(payload.current_password, admin["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")
    supabase.table("admin_users").update({"password_hash": hash_password(payload.new_password)}).eq("id", admin["id"]).execute()
    return {"ok": True, "message": "Password changed successfully"}


@router.post("/client/register")
def client_register(payload: ClientRegisterIn):
    existing = get_client_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A client account already exists for this email")

    client_row = {
        "name": payload.name.strip(),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "company_name": payload.company_name,
        "phone": payload.phone,
        "is_active": True,
    }
    created = supabase.table("users").insert(client_row).execute().data[0]

    # Also create/update a lead record so the admin can follow up with the registered client.
    try:
        supabase.table("leads").insert({
            "user_id": created["id"],
            "name": created.get("name") or payload.name,
            "email": created["email"],
            "status": "registered",
            "paid": False,
        }).execute()
    except Exception as exc:
        print(f"Client lead creation skipped: {exc}")

    token = create_access_token(created["id"], {"email": created["email"], "role": "client"}, token_type="client")
    return {
        "access_token": token,
        "token_type": "bearer",
        "client": {
            "id": created["id"],
            "name": created.get("name"),
            "email": created["email"],
            "company_name": created.get("company_name"),
            "phone": created.get("phone"),
        },
    }


@router.post("/client/login")
def client_login(payload: ClientLoginIn):
    client = get_client_by_email(payload.email)
    if not client or not verify_password(payload.password, client["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not client.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Client account inactive")
    token = create_access_token(client["id"], {"email": client["email"], "role": "client"}, token_type="client")
    return {
        "access_token": token,
        "token_type": "bearer",
        "client": {
            "id": client["id"],
            "name": client.get("name"),
            "email": client["email"],
            "company_name": client.get("company_name"),
            "phone": client.get("phone"),
        },
    }


@router.get("/client/me")
def client_me(client: dict = Depends(get_current_client)):
    return {
        "id": client["id"],
        "name": client.get("name"),
        "email": client["email"],
        "company_name": client.get("company_name"),
        "phone": client.get("phone"),
    }


@router.post("/client/change-password")
def client_change_password(payload: ClientChangePasswordIn, client: dict = Depends(get_current_client)):
    if not verify_password(payload.current_password, client["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")
    supabase.table("users").update({"password_hash": hash_password(payload.new_password)}).eq("id", client["id"]).execute()
    return {"ok": True, "message": "Password changed successfully"}
