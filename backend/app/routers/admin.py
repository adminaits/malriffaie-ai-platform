from fastapi import APIRouter, Depends, HTTPException
from app.db import supabase
from app.models import ProductIn, ServiceIn, AiSettingsIn, ChatSettingsIn
from app.services.huggingface import test_hf_connection
from app.auth import get_current_admin

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)]
)

TABLES = {
    "products",
    "services",
    "knowledge_base",
    "bookings",
    "payments",
    "leads",
    "chat_messages",
    "ai_settings",
    "chat_settings",
    "google_drive_widgets",
    "booking_settings",
    "payment_settings",
    "email_settings",
}


def ensure_table(table: str):
    if table not in TABLES:
        raise HTTPException(404, "Unknown table")


# Specific admin actions must be registered before the generic /{table} routes.
@router.post("/products/typed")
def create_product(payload: ProductIn):
    result = supabase.table("products").insert(payload.model_dump()).execute()
    return result.data[0] if result.data else {"ok": False, "message": "Product was not created"}


@router.post("/services/typed")
def create_service(payload: ServiceIn):
    result = supabase.table("services").insert(payload.model_dump()).execute()
    return result.data[0] if result.data else {"ok": False, "message": "Service was not created"}


@router.post("/ai-settings")
def save_ai_settings(payload: AiSettingsIn):
    result = supabase.table("ai_settings").insert(payload.model_dump()).execute()
    return result.data[0] if result.data else {"ok": False, "message": "AI settings were not saved"}


@router.post("/chat-settings")
def save_chat_settings(payload: ChatSettingsIn):
    result = supabase.table("chat_settings").insert(payload.model_dump()).execute()
    return result.data[0] if result.data else {"ok": False, "message": "Chat settings were not saved"}


@router.post("/test-huggingface")
async def test_huggingface(payload: dict):
    """
    Safely test Hugging Face connection.

    This endpoint intentionally catches errors and returns JSON instead of crashing.
    That prevents the frontend from showing a misleading CORS / Failed to fetch error
    when the real issue is an invalid token, bad model, or bad endpoint URL.
    """
    try:
        token = (
            payload.get("hugging_face_token")
            or payload.get("hf_token")
            or payload.get("token")
        )

        model = (
            payload.get("model_name")
            or payload.get("model")
            or payload.get("default_model")
            or payload.get("selected_model")
            or "HuggingFaceH4/zephyr-7b-beta"
        )

        endpoint = (
            payload.get("custom_hf_endpoint")
            or payload.get("custom_endpoint_url")
            or payload.get("endpoint_url")
            or payload.get("endpoint")
            or None
        )

        if token is not None:
            token = str(token).strip()

        if model is not None:
            model = str(model).strip()

        if endpoint is not None:
            endpoint = str(endpoint).strip()
            if endpoint == "":
                endpoint = None

        if not token:
            return {
                "ok": False,
                "message": "Hugging Face token is missing. Add a valid hf_ token in AI settings.",
                "error": "missing_hugging_face_token",
            }

        if not model:
            model = "HuggingFaceH4/zephyr-7b-beta"

        result = await test_hf_connection(token, model, endpoint)

        return {
            "ok": True,
            "message": "Hugging Face test completed.",
            "result": result,
        }

    except Exception as exc:
        return {
            "ok": False,
            "message": "Hugging Face connection failed.",
            "error": str(exc),
        }


@router.get("/leads/export.csv")
def export_leads_csv():
    rows = supabase.table("leads").select("*").execute().data or []

    import csv
    import io

    out = io.StringIO()

    if rows:
        writer = csv.DictWriter(out, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    return {"csv": out.getvalue()}


@router.get("/{table}")
def list_rows(table: str):
    ensure_table(table)

    return (
        supabase
        .table(table)
        .select("*")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
        .data
    )


@router.post("/{table}")
def create_row(table: str, payload: dict):
    ensure_table(table)

    result = supabase.table(table).insert(payload).execute()
    return result.data[0] if result.data else {"ok": False, "message": "Row was not created"}


@router.patch("/{table}/{row_id}")
def update_row(table: str, row_id: str, payload: dict):
    ensure_table(table)

    result = supabase.table(table).update(payload).eq("id", row_id).execute()
    return result.data[0] if result.data else {"ok": False, "message": "Row was not updated"}


@router.delete("/{table}/{row_id}")
def delete_row(table: str, row_id: str):
    ensure_table(table)

    supabase.table(table).delete().eq("id", row_id).execute()
    return {"ok": True}
