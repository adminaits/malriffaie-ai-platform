from fastapi import APIRouter, Request, Depends
from app.db import supabase
from app.models import ChatRequest, ChatResponse, LeadIn, BookingIn
from app.services.rag import answer_chat
from app.auth import get_current_client, get_current_admin
import hashlib


router = APIRouter(prefix="/api", tags=["public"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/settings/chat")
def chat_settings():
    res = (
        supabase
        .table("chat_settings")
        .select("*")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    return (res.data or [{}])[0]


@router.get("/products")
def products():
    return (
        supabase
        .table("products")
        .select("*")
        .eq("available", True)
        .order("created_at", desc=True)
        .execute()
        .data
    )


@router.get("/services")
def services():
    return (
        supabase
        .table("services")
        .select("*")
        .eq("available", True)
        .order("created_at", desc=True)
        .execute()
        .data
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request):
    """
    Public chat endpoint.

    Public users can access:
    - products
    - services
    - public knowledge base

    Public users cannot access:
    - internal company wikis
    - private Google Drive knowledge
    """
    try:
        ip = request.client.host if request.client else "unknown"
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()

        return await answer_chat(
            payload.message,
            visitor_id=payload.visitor_id,
            lang=payload.lang,
            ip_hash=ip_hash,
            client_logged_in=False,
        )

    except Exception as exc:
        return {
            "answer": f"Chat backend error: {str(exc)}",
            "products": [],
            "sources": [],
        }


@router.post("/chat/client", response_model=ChatResponse)
async def client_chat(
    payload: ChatRequest,
    request: Request,
    client=Depends(get_current_client),
):
    """
    Logged-in client chat endpoint.

    Logged-in clients can access:
    - products
    - services
    - public knowledge base
    - private/internal company wiki knowledge
    """
    try:
        ip = request.client.host if request.client else "unknown"
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()

        return await answer_chat(
            payload.message,
            visitor_id=payload.visitor_id,
            lang=payload.lang,
            ip_hash=ip_hash,
            client_logged_in=True,
        )

    except Exception as exc:
        return {
            "answer": f"Client chat backend error: {str(exc)}",
            "products": [],
            "sources": [],
        }


@router.post("/chat/admin", response_model=ChatResponse)
async def admin_chat(
    payload: ChatRequest,
    request: Request,
    admin=Depends(get_current_admin),
):
    """
    Logged-in admin chat endpoint.

    Admins can access:
    - products
    - services
    - public knowledge base
    - private/internal company wiki knowledge
    """
    try:
        ip = request.client.host if request.client else "unknown"
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()

        return await answer_chat(
            payload.message,
            visitor_id=payload.visitor_id,
            lang=payload.lang,
            ip_hash=ip_hash,
            client_logged_in=True,
        )

    except Exception as exc:
        return {
            "answer": f"Admin chat backend error: {str(exc)}",
            "products": [],
            "sources": [],
        }


@router.post("/leads")
def create_lead(payload: LeadIn):
    res = supabase.table("leads").insert(payload.model_dump()).execute()
    return res.data[0]


@router.post("/bookings")
def create_booking(payload: BookingIn):
    res = supabase.table("bookings").insert(payload.model_dump()).execute()
    return res.data[0]
