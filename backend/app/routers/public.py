from fastapi import APIRouter, Request, Depends
from app.db import supabase
from app.models import ChatRequest, ChatResponse, LeadIn, BookingIn
from app.services.rag import answer_chat
from app.auth import get_current_client, get_current_admin
import hashlib


router = APIRouter(prefix="/api", tags=["public"])


def _get_client_data(client):
    """
    Some auth functions return the client directly:
    {"id": "...", "email": "..."}

    Others may return:
    {"client": {"id": "...", "email": "..."}}

    This helper supports both safely.
    """
    if isinstance(client, dict) and client.get("client"):
        return client.get("client")

    return client


def _get_client_id(client):
    client_data = _get_client_data(client)

    if isinstance(client_data, dict):
        return client_data.get("id") or client_data.get("client_id") or client_data.get("email")

    return None


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

        client_id = _get_client_id(client)

        visitor_id = payload.visitor_id

        if client_id:
            visitor_id = f"client:{client_id}"

        return await answer_chat(
            payload.message,
            visitor_id=visitor_id,
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


@router.get("/chat/client/history")
def client_chat_history(client=Depends(get_current_client)):
    """
    Logged-in client chat history endpoint.

    This returns the last 100 chat messages saved for this client.
    The frontend uses this to show previous chat history in the client dashboard sidebar.
    """
    try:
        client_id = _get_client_id(client)

        if not client_id:
            return []

        rows = (
            supabase
            .table("chat_messages")
            .select("*")
            .eq("visitor_id", f"client:{client_id}")
            .order("created_at", desc=False)
            .limit(100)
            .execute()
            .data
            or []
        )

        return rows

    except Exception:
        return []


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
