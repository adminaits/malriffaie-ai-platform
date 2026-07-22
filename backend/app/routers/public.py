from fastapi import APIRouter, Request
from app.db import supabase
from app.models import ChatRequest, ChatResponse, LeadIn, BookingIn
from app.services.rag import answer_chat
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
    try:
        ip = request.client.host if request.client else "unknown"
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()

        return await answer_chat(
            payload.message,
            visitor_id=payload.visitor_id,
            lang=payload.lang,
            ip_hash=ip_hash,
        )

    except Exception as exc:
        # This prevents the frontend from only showing "chat service unavailable"
        # and helps us see the real backend error during testing.
        return {
            "answer": f"Chat backend error: {str(exc)}",
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
