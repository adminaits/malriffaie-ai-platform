from fastapi import APIRouter, Depends, HTTPException
from app.db import supabase
from app.models import ProductIn, ServiceIn, AiSettingsIn, ChatSettingsIn
from app.services.huggingface import test_hf_connection
from app.auth import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(get_current_admin)])

TABLES = {
    "products", "services", "knowledge_base", "bookings", "payments", "leads", "chat_messages",
    "ai_settings", "chat_settings", "google_drive_widgets", "booking_settings", "payment_settings", "email_settings"
}


def ensure_table(table: str):
    if table not in TABLES:
        raise HTTPException(404, "Unknown table")


# Specific admin actions must be registered before the generic /{table} routes.
@router.post("/products/typed")
def create_product(payload: ProductIn):
    return supabase.table("products").insert(payload.model_dump()).execute().data[0]


@router.post("/services/typed")
def create_service(payload: ServiceIn):
    return supabase.table("services").insert(payload.model_dump()).execute().data[0]


@router.post("/ai-settings")
def save_ai_settings(payload: AiSettingsIn):
    return supabase.table("ai_settings").insert(payload.model_dump()).execute().data[0]


@router.post("/chat-settings")
def save_chat_settings(payload: ChatSettingsIn):
    return supabase.table("chat_settings").insert(payload.model_dump()).execute().data[0]


@router.post("/test-huggingface")
async def test_huggingface(payload: dict):
    token = payload.get("hugging_face_token")
    model = payload.get("model_name")
    endpoint = payload.get("custom_endpoint_url")
    if not token or not model:
        raise HTTPException(400, "Token and model_name are required")
    return await test_hf_connection(token, model, endpoint)


@router.get("/leads/export.csv")
def export_leads_csv():
    rows = supabase.table("leads").select("*").execute().data or []
    import csv, io
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return {"csv": out.getvalue()}


@router.get("/{table}")
def list_rows(table: str):
    ensure_table(table)
    return supabase.table(table).select("*").order("created_at", desc=True).limit(500).execute().data


@router.post("/{table}")
def create_row(table: str, payload: dict):
    ensure_table(table)
    return supabase.table(table).insert(payload).execute().data[0]


@router.patch("/{table}/{row_id}")
def update_row(table: str, row_id: str, payload: dict):
    ensure_table(table)
    return supabase.table(table).update(payload).eq("id", row_id).execute().data[0]


@router.delete("/{table}/{row_id}")
def delete_row(table: str, row_id: str):
    ensure_table(table)
    supabase.table(table).delete().eq("id", row_id).execute()
    return {"ok": True}
